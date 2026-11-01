import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.backends.signals import connection_created
from django.test import LiveServerTestCase, override_settings
from rest_framework.authtoken.models import Token

from reservations.models import Reservation, ReservationRequest, Room


NOW = datetime(2030, 1, 1, tzinfo=UTC)
START = datetime(2030, 1, 2, 9, tzinfo=ZoneInfo("Asia/Tehran"))


@override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=180)
class ReservationHTTPConcurrencyTests(LiveServerTestCase):
    """Real HTTP, real tokens, and committed PostgreSQL connections per worker."""

    def setUp(self):
        self.room = Room.objects.create(name="Room A", capacity=3)
        self.other_room = Room.objects.create(name="Room B", capacity=3)
        self.tokens = []
        for index in range(10):
            user = get_user_model().objects.create_user(username=f"employee-{index}")
            self.tokens.append(Token.objects.create(user=user).key)
        self.clock_patch = patch("reservations.validators.timezone.now", return_value=NOW)
        self.clock = self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.backend_pids = set()
        self.pid_lock = Lock()
        self.connected = Event()
        connection_created.connect(self.record_connection, weak=False)
        self.addCleanup(connection_created.disconnect, self.record_connection)

    def record_connection(self, sender, connection, **kwargs):
        if connection.alias == "default":
            with self.pid_lock:
                self.backend_pids.add(connection.connection.info.backend_pid)
            self.connected.set()

    def post_reservation(self, key, *, token=None, room=None, barrier=None):
        if barrier is not None:
            barrier.wait(timeout=10)
        payload = {
            "room": self.room.pk if room is None else room,
            "start_at": START.isoformat(),
            "end_at": (START + timedelta(hours=1)).isoformat(),
            "attendees_count": 3,
        }
        request = Request(
            f"{self.live_server_url}/api/reservations/",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token {token or self.tokens[0]}",
                "Idempotency-Key": key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_ten_users_same_interval_only_one_creation_and_nine_409s(self):
        barrier = Barrier(10)
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(
                    self.post_reservation, f"request-{index}",
                    token=self.tokens[index], barrier=barrier,
                )
                for index in range(10)
            ]
            results = [future.result(timeout=20) for future in futures]
        statuses = [code for code, _ in results]
        self.assertEqual(statuses.count(201), 1, results)
        self.assertEqual(statuses.count(409), 9, results)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(ReservationRequest.objects.count(), 1)
        self.assertEqual(len(self.backend_pids), 10)

    def test_ten_identical_keys_replay_one_creation_with_same_response(self):
        barrier = Barrier(10)
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(self.post_reservation, "same-key", barrier=barrier)
                for _ in range(10)
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual([code for code, _ in results], [201] * 10)
        self.assertTrue(all(body == results[0][1] for _, body in results))
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(ReservationRequest.objects.count(), 1)
        self.assertEqual(len(self.backend_pids), 10)

    def test_same_user_key_for_different_rooms_cannot_create_two_reservations(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.post_reservation, "same-key", room=room.pk, barrier=barrier)
                for room in (self.room, self.other_room)
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(code for code, _ in results), [201, 409], results)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(ReservationRequest.objects.count(), 1)

    def test_different_rooms_with_different_keys_can_both_be_reserved(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.post_reservation, f"room-{room.pk}", room=room.pk, barrier=barrier)
                for room in (self.room, self.other_room)
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual([code for code, _ in results], [201, 201], results)
        self.assertEqual(Reservation.objects.count(), 2)
        self.assertEqual(ReservationRequest.objects.count(), 2)

    def assert_http_worker_waiting_for_room_lock(self):
        self.assertTrue(self.connected.wait(timeout=5), "HTTP worker did not connect to PostgreSQL")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.pid_lock:
                pids = list(self.backend_pids)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE pid = ANY(%s) AND wait_event_type = 'Lock'",
                    [pids],
                )
                if any("reservations_room" in query and "FOR UPDATE" in query for (query,) in cursor.fetchall()):
                    return
            time.sleep(0.01)
        self.fail("HTTP worker was not observed waiting on SELECT FOR UPDATE of the room")

    def check_room_update_is_rechecked(self, **updates):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked_room = Room.objects.select_for_update().get(pk=self.room.pk)
                for field, value in updates.items():
                    setattr(locked_room, field, value)
                locked_room.save(update_fields=list(updates))
                future = executor.submit(self.post_reservation, "waiting-request")
                self.assert_http_worker_waiting_for_room_lock()
            code, body = future.result(timeout=20)
        self.assertEqual(code, 400, body)
        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(ReservationRequest.objects.count(), 0)

    def test_room_deactivated_while_request_waits_is_rejected(self):
        self.check_room_update_is_rechecked(is_active=False)

    def test_capacity_reduced_while_request_waits_is_rejected(self):
        self.check_room_update_is_rechecked(capacity=2)

    def test_start_time_is_revalidated_after_waiting_for_room_lock(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Room.objects.select_for_update().get(pk=self.room.pk)
                future = executor.submit(self.post_reservation, "waiting-request")
                self.assert_http_worker_waiting_for_room_lock()
                self.clock.return_value = START + timedelta(minutes=1)
            code, body = future.result(timeout=20)
        self.assertEqual(code, 400, body)
        self.assertIn("start_at", body)
        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(ReservationRequest.objects.count(), 0)
