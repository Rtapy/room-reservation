from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone as django_timezone

from reservations.models import Reservation, Room


class ModelConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="employee")
        cls.other_user = get_user_model().objects.create_user(username="other-employee")
        cls.room = Room.objects.create(name="Room A", capacity=6)
        cls.other_room = Room.objects.create(name="Room B", capacity=6)
        cls.start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)

    def create_reservation(self, **overrides):
        values = {
            "room": self.room,
            "user": self.user,
            "start_at": self.start,
            "end_at": self.start + timedelta(hours=1),
            "attendees_count": 3,
        }
        values.update(overrides)
        return Reservation.objects.create(**values)

    @contextmanager
    def assert_constraint(self, name):
        with self.assertRaises(IntegrityError) as error:
            with transaction.atomic():
                yield
        self.assertEqual(error.exception.__cause__.diag.constraint_name, name)

    def test_custom_positive_checks_reject_zero_capacity_and_attendees(self):
        with self.assert_constraint("room_capacity_positive"):
            Room.objects.create(name="Zero capacity", capacity=0)
        with self.assert_constraint("reservation_attendees_positive"):
            self.create_reservation(attendees_count=0)

    def test_end_must_be_strictly_after_start(self):
        for end in (self.start, self.start - timedelta(minutes=1)):
            with self.subTest(end=end):
                with self.assert_constraint("reservation_time_order"):
                    self.create_reservation(end_at=end)

    def test_status_and_cancellation_timestamp_must_agree(self):
        invalid_states = [
            {"status": Reservation.Status.CANCELLED},
            {"cancelled_at": django_timezone.now()},
            {"status": "pending"},
            {"status": "pending", "cancelled_at": django_timezone.now()},
        ]
        for values in invalid_states:
            with self.subTest(values=values):
                with self.assert_constraint("reservation_valid_state"):
                    self.create_reservation(**values)

    def test_overlapping_reservations_rejected_for_any_user(self):
        self.create_reservation()
        # Exact match, partial overlaps, contained, and containing intervals.
        for start_offset, end_offset in [(0, 60), (-30, 30), (30, 90), (15, 45), (-15, 75)]:
            with self.subTest(offsets=(start_offset, end_offset)):
                with self.assert_constraint("reservation_no_overlap"):
                    self.create_reservation(
                        user=self.other_user,
                        start_at=self.start + timedelta(minutes=start_offset),
                        end_at=self.start + timedelta(minutes=end_offset),
                    )

    def test_exclusion_allows_adjacent_different_room_and_cancelled_intervals(self):
        self.create_reservation()
        self.create_reservation(start_at=self.start - timedelta(hours=1), end_at=self.start)
        self.create_reservation(
            start_at=self.start + timedelta(hours=1), end_at=self.start + timedelta(hours=2)
        )
        self.create_reservation(room=self.other_room)
        self.create_reservation(
            status=Reservation.Status.CANCELLED, cancelled_at=django_timezone.now()
        )
        self.assertEqual(Reservation.objects.count(), 5)

    def test_room_and_user_with_reservation_cannot_be_deleted(self):
        self.create_reservation(status=Reservation.Status.CANCELLED, cancelled_at=django_timezone.now())
        for owner in (self.room, self.user):
            with self.subTest(model=type(owner).__name__):
                with self.assertRaises(ProtectedError):
                    owner.delete()
        self.assertEqual(Reservation.objects.count(), 1)


class ConcurrentConstraintTests(TransactionTestCase):
    def test_only_one_of_ten_concurrent_overlapping_inserts_succeeds(self):
        user = get_user_model().objects.create_user(username="employee")
        room = Room.objects.create(name="Concurrent room", capacity=6)
        start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
        barrier = Barrier(10)

        def insert_reservation():
            close_old_connections()
            try:
                # Each worker opens its own PostgreSQL connection before the barrier.
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pid = cursor.fetchone()[0]
                barrier.wait(timeout=15)
                try:
                    with transaction.atomic():
                        with connections["default"].cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '10s'")
                            cursor.execute("SET LOCAL statement_timeout = '15s'")
                        Reservation.objects.create(
                            room_id=room.pk,
                            user_id=user.pk,
                            start_at=start,
                            end_at=start + timedelta(hours=1),
                            attendees_count=3,
                        )
                    return backend_pid, "created"
                except IntegrityError as error:
                    return backend_pid, error.__cause__.diag.constraint_name
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(insert_reservation) for _ in range(10)]
            results = [future.result(timeout=30) for future in futures]

        self.assertEqual(len({pid for pid, _ in results}), 10)
        outcomes = [outcome for _, outcome in results]
        self.assertEqual(outcomes.count("created"), 1)
        self.assertEqual(outcomes.count("reservation_no_overlap"), 9)
        self.assertEqual(Reservation.objects.filter(status=Reservation.Status.CONFIRMED).count(), 1)
