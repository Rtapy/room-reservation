from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reservations.models import Reservation, ReservationRequest, Room


NOW = datetime(2030, 1, 1, tzinfo=UTC)
START = datetime(2030, 1, 2, 9, tzinfo=ZoneInfo("Asia/Tehran"))


@override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=180)
class ReservationCreationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = get_user_model().objects.create_user(username="employee")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        cls.tokens = {
            user.pk: Token.objects.create(user=user).key
            for user in (cls.employee, cls.other, cls.staff)
        }
        cls.room = Room.objects.create(name="Room A", capacity=3)
        cls.other_room = Room.objects.create(name="Room B", capacity=3)

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[self.employee.pk]}")
        clock = patch("reservations.validators.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def payload(self, **overrides):
        payload = {
            "room": self.room.pk,
            "start_at": START.isoformat(),
            "end_at": (START + timedelta(hours=1)).isoformat(),
            "attendees_count": 3,
        }
        payload.update(overrides)
        return payload

    def reserve(self, key="request-1", **overrides):
        headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
        return self.client.post(
            reverse("reservation-list"), self.payload(**overrides), format="json", **headers
        )

    def assert_no_writes(self):
        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(ReservationRequest.objects.count(), 0)

    def test_success_creates_reservation_and_response_record(self):
        response = self.reserve()
        self.assertEqual(response.status_code, 201)
        reservation = Reservation.objects.get()
        record = ReservationRequest.objects.get()
        self.assertEqual(reservation.user_id, self.employee.pk)
        self.assertEqual(reservation.room_id, self.room.pk)
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(reservation.attendees_count, self.room.capacity)
        self.assertEqual(record.reservation_id, reservation.pk)
        self.assertEqual(record.response_body, response.json())
        self.assertEqual(response.data["id"], reservation.pk)

    def test_owner_and_initial_state_are_always_assigned_by_server(self):
        for user, room in ((self.employee, self.room), (self.staff, self.other_room)):
            with self.subTest(user=user.username):
                self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[user.pk]}")
                response = self.reserve(
                    room=room.pk, user=self.other.pk, status="cancelled", cancelled_at=NOW.isoformat()
                )
                self.assertEqual(response.status_code, 201)
                reservation = Reservation.objects.get(pk=response.data["id"])
                self.assertEqual(reservation.user_id, user.pk)
                self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
                self.assertIsNone(reservation.cancelled_at)

    def test_unauthenticated_creation_is_rejected(self):
        for credentials in ({}, {"HTTP_AUTHORIZATION": "Token invalid"}):
            with self.subTest(credentials=bool(credentials)):
                self.client.credentials(**credentials)
                self.assertEqual(self.reserve().status_code, 401)
        self.assert_no_writes()

    def test_idempotency_key_is_required_and_validated(self):
        for key in (None, "", " ", "has space", "x" * 256, "bad\x00key"):
            with self.subTest(length=None if key is None else len(key)):
                response = self.reserve(key=key)
                self.assertEqual(response.status_code, 400)
                self.assertIn("Idempotency-Key", response.data)
        self.assert_no_writes()

    def test_equivalent_timezone_and_numeric_inputs_replay_same_response(self):
        first = self.reserve()
        second = self.reserve(
            room=str(self.room.pk), attendees_count="3",
            start_at=START.astimezone(UTC).isoformat(),
            end_at=(START + timedelta(hours=1)).astimezone(UTC).isoformat(),
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Reservation.objects.count(), 1)

    def test_same_key_with_different_effective_data_returns_409(self):
        self.assertEqual(self.reserve().status_code, 201)
        for changes in (
            {"room": self.other_room.pk}, {"attendees_count": 2},
            {"start_at": (START + timedelta(minutes=15)).isoformat()},
            {"end_at": (START + timedelta(minutes=90)).isoformat()},
        ):
            with self.subTest(fields=tuple(changes)):
                self.assertEqual(self.reserve(**changes).status_code, 409)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(ReservationRequest.objects.count(), 1)

    def test_keys_are_scoped_to_each_user(self):
        first = self.reserve()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[self.other.pk]}")
        second = self.reserve(room=self.other_room.pk)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data["id"], second.data["id"])
        self.assertEqual(ReservationRequest.objects.count(), 2)

    def test_replay_survives_cancellation_and_changed_runtime_rules(self):
        first = self.reserve()
        cancelled = self.client.post(reverse("reservation-cancel", args=[first.data["id"]]))
        self.assertEqual(cancelled.status_code, 200)
        self.room.is_active = False
        self.room.capacity = 1
        self.room.save()
        with patch("reservations.validators.timezone.now", return_value=START + timedelta(days=1)):
            with override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=30):
                second = self.reserve()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Reservation.objects.get().status, Reservation.Status.CANCELLED)

    def test_overlapping_reservation_returns_409_and_rolls_back_key(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[self.other.pk]}")
        response = self.reserve(key="other-request")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertFalse(ReservationRequest.objects.filter(key="other-request").exists())

    def test_adjacent_and_other_room_reservations_are_allowed(self):
        self.assertEqual(self.reserve().status_code, 201)
        adjacent = self.reserve(
            key="adjacent", start_at=(START + timedelta(hours=1)).isoformat(),
            end_at=(START + timedelta(hours=2)).isoformat(),
        )
        other = self.reserve(key="other-room", room=self.other_room.pk)
        self.assertEqual(adjacent.status_code, 201)
        self.assertEqual(other.status_code, 201)
        self.assertEqual(Reservation.objects.count(), 3)

    def test_cancelled_reservation_does_not_block_new_creation(self):
        original = self.reserve()
        self.assertEqual(original.status_code, 201)
        cancelled = self.client.post(reverse("reservation-cancel", args=[original.data["id"]]))
        self.assertEqual(cancelled.status_code, 200)
        available = self.client.get(
            reverse("room-available"),
            {"start_at": START.isoformat(), "end_at": (START + timedelta(hours=1)).isoformat(), "attendees_count": 3},
        )
        self.assertEqual(available.status_code, 200)
        self.assertIn(self.room.pk, {room["id"] for room in available.data})
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[self.other.pk]}")
        self.assertEqual(self.reserve(key="new-reservation").status_code, 201)
        self.assertEqual(Reservation.objects.count(), 2)

    def test_rejected_room_conditions_do_not_consume_key(self):
        self.assertEqual(self.reserve(room=self.other_room.pk + 1000).status_code, 404)
        self.assert_no_writes()
        self.room.is_active = False
        self.room.save()
        self.assertEqual(self.reserve().status_code, 400)
        self.assert_no_writes()
        self.room.is_active = True
        self.room.save()
        self.assertEqual(self.reserve(attendees_count=4).status_code, 400)
        self.assert_no_writes()
        self.assertEqual(self.reserve().status_code, 201)

    def test_invalid_creation_fields_are_rejected(self):
        for field, value in (
            ("room", 0), ("room", "invalid"), ("attendees_count", 0),
            ("start_at", "invalid"), ("start_at", "2030-01-02T09:00:00"),
        ):
            with self.subTest(field=field, value=value):
                response = self.reserve(**{field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        for field in self.payload():
            payload = self.payload()
            del payload[field]
            response = self.client.post(
                reverse("reservation-list"), payload, format="json", HTTP_IDEMPOTENCY_KEY="request-1"
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)
        self.assert_no_writes()

    def test_creation_applies_shared_time_validation(self):
        for start, end in (
            (START - timedelta(days=2), START - timedelta(days=2) + timedelta(hours=1)),
            (START.replace(hour=7), START.replace(hour=8)),
        ):
            with self.subTest(start=start, end=end):
                self.assertEqual(self.reserve(start_at=start.isoformat(), end_at=end.isoformat()).status_code, 400)
        self.assert_no_writes()

    def test_database_exclusion_violation_is_also_translated_to_409(self):
        self.assertEqual(self.reserve().status_code, 201)
        # Bypass the preflight check, but let PostgreSQL perform the actual insert.
        with patch("reservations.services.Reservation.objects.filter") as overlaps:
            overlaps.return_value.exists.return_value = False
            response = self.reserve(key="constraint-fallback")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertFalse(ReservationRequest.objects.filter(key="constraint-fallback").exists())

    def test_response_persistence_failure_rolls_back_reservation_and_key(self):
        original_save = ReservationRequest.save

        def fail_on_response(record, *args, **kwargs):
            if record.response_body is not None:
                raise IntegrityError("unrelated response persistence failure")
            return original_save(record, *args, **kwargs)

        with patch.object(ReservationRequest, "save", new=fail_on_response):
            with self.assertRaises(IntegrityError):
                self.reserve()
        self.assert_no_writes()
