from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reservations.models import Reservation, Room


COMPANY_TIMEZONE = ZoneInfo("Asia/Tehran")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


@override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=180)
class AvailabilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = get_user_model().objects.create_user(username="employee")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.token = Token.objects.create(user=cls.employee)
        cls.free = Room.objects.create(name="A Free", capacity=8)
        cls.exact = Room.objects.create(name="B Exact", capacity=3)
        cls.small = Room.objects.create(name="C Small", capacity=2)
        cls.inactive = Room.objects.create(name="D Inactive", capacity=20, is_active=False)
        cls.busy = Room.objects.create(name="E Busy", capacity=20)
        cls.cancelled = Room.objects.create(name="F Cancelled", capacity=20)
        cls.start = datetime(2030, 1, 4, 9, tzinfo=COMPANY_TIMEZONE)  # Friday is allowed.
        cls.end = cls.start + timedelta(hours=1)
        Reservation.objects.create(
            room=cls.busy, user=cls.other, start_at=cls.start,
            end_at=cls.end, attendees_count=2,
        )
        Reservation.objects.create(
            room=cls.cancelled, user=cls.other, start_at=cls.start,
            end_at=cls.end, attendees_count=2,
            status=Reservation.Status.CANCELLED, cancelled_at=NOW,
        )
        # A non-conflicting row must not hide a free room or undo a conflict.
        for room in (cls.free, cls.busy):
            Reservation.objects.create(
                room=room, user=cls.other, start_at=cls.start + timedelta(hours=2),
                end_at=cls.end + timedelta(hours=2), attendees_count=2,
            )

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        clock = patch("reservations.validators.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def search(self, **overrides):
        params = {
            "start_at": self.start.isoformat(),
            "end_at": self.end.isoformat(),
            "attendees_count": 3,
        }
        params.update(overrides)
        return self.client.get(reverse("room-available"), params)

    def test_search_returns_only_active_rooms_with_enough_capacity_and_no_conflict(self):
        self.assertEqual(self.start.weekday(), 4)
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([room["id"] for room in response.data], [self.free.pk, self.exact.pk, self.cancelled.pk])
        self.assertEqual(set(response.data[0]), {"id", "name", "capacity", "is_active"})

    def test_no_matching_rooms_returns_empty_array(self):
        response = self.search(attendees_count=100)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_query_parameters_are_required_and_validated(self):
        params = {"start_at": self.start.isoformat(), "end_at": self.end.isoformat(), "attendees_count": 3}
        for field in params:
            with self.subTest(field=field):
                response = self.client.get(reverse("room-available"), {key: value for key, value in params.items() if key != field})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)
        for field, value in (
            ("start_at", "invalid"), ("end_at", "2030-13-02T10:00:00Z"),
            ("attendees_count", 0), ("attendees_count", -1),
            ("attendees_count", "2.5"),
        ):
            with self.subTest(field=field, value=value):
                response = self.search(**{field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_timezone_inputs_require_offsets_and_use_company_time(self):
        for field in ("start_at", "end_at"):
            with self.subTest(field=field):
                response = self.search(**{field: "2030-01-02T09:00:00"})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)
        expected = self.search().json()
        response = self.search(
            start_at=self.start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            end_at=self.end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        # These UTC working hours are outside Tehran working hours.
        response = self.search(start_at="2030-01-04T17:00:00Z", end_at="2030-01-04T18:00:00Z")
        self.assertEqual(response.status_code, 400)

    def test_availability_applies_shared_time_validation(self):
        for start, end in (
            (self.start - timedelta(days=4), self.end - timedelta(days=4)),
            (self.start, self.start + timedelta(minutes=14)),
        ):
            with self.subTest(start=start, end=end):
                response = self.search(start_at=start.isoformat(), end_at=end.isoformat())
                self.assertEqual(response.status_code, 400)

    def test_all_overlap_shapes_exclude_the_room(self):
        for start_offset, end_offset in ((0, 60), (-30, 30), (30, 90), (15, 45), (-15, 75)):
            with self.subTest(offsets=(start_offset, end_offset)):
                response = self.search(
                    start_at=(self.start + timedelta(minutes=start_offset)).isoformat(),
                    end_at=(self.start + timedelta(minutes=end_offset)).isoformat(),
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertNotIn(self.busy.pk, {room["id"] for room in response.data})

    def test_adjacent_intervals_on_either_side_do_not_conflict(self):
        for start, end in ((self.start - timedelta(hours=1), self.start), (self.end, self.end + timedelta(hours=1))):
            with self.subTest(start=start):
                response = self.search(start_at=start.isoformat(), end_at=end.isoformat())
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn(self.busy.pk, {room["id"] for room in response.data})

    def test_search_does_not_write_or_hold_a_reservation(self):
        before = Reservation.objects.count()
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Reservation.objects.count(), before)
        Reservation.objects.create(
            room=self.free, user=self.other, start_at=self.start, end_at=self.end, attendees_count=2,
        )
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.free.pk, {room["id"] for room in response.data})
