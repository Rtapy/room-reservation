from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reservations.models import Reservation, Room
from reservations.validators import validate_reservation_window


COMPANY_TIMEZONE = ZoneInfo("Asia/Tehran")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


@override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=180)
class AvailabilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = get_user_model().objects.create_user(username="employee")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        cls.token = Token.objects.create(user=cls.employee)
        cls.staff_token = Token.objects.create(user=cls.staff)
        cls.free = Room.objects.create(name="A Free", capacity=8)
        cls.exact = Room.objects.create(name="B Exact", capacity=3)
        cls.small = Room.objects.create(name="C Small", capacity=2)
        cls.inactive = Room.objects.create(name="D Inactive", capacity=20, is_active=False)
        cls.busy = Room.objects.create(name="E Busy", capacity=20)
        cls.cancelled = Room.objects.create(name="F Cancelled", capacity=20)
        cls.start = datetime(2030, 1, 2, 9, tzinfo=COMPANY_TIMEZONE)
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

    def test_static_route_resolves_to_availability_action(self):
        match = resolve("/api/rooms/available/")
        self.assertEqual(match.url_name, "room-available")
        self.assertEqual(match.func.actions["get"], "available")

    def test_search_returns_only_active_rooms_with_enough_capacity_and_no_conflict(self):
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([room["id"] for room in response.data], [self.free.pk, self.exact.pk, self.cancelled.pk])
        self.assertEqual(set(response.data[0]), {"id", "name", "capacity", "is_active"})

    def test_no_matching_rooms_returns_empty_array(self):
        response = self.search(attendees_count=100)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_missing_or_invalid_token_is_rejected(self):
        for credentials in ({}, {"HTTP_AUTHORIZATION": "Token invalid"}):
            with self.subTest(authenticated=bool(credentials)):
                self.client.credentials(**credentials)
                self.assertEqual(self.search().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_staff_search_has_the_same_availability_rules(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token.key}")
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({room["id"] for room in response.data}, {self.free.pk, self.exact.pk, self.cancelled.pk})

    def test_all_search_parameters_are_required(self):
        params = {"start_at": self.start.isoformat(), "end_at": self.end.isoformat(), "attendees_count": 3}
        for field in params:
            with self.subTest(field=field):
                response = self.client.get(reverse("room-available"), {key: value for key, value in params.items() if key != field})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)

    def test_invalid_dates_and_attendee_counts_are_rejected(self):
        for field, value in (
            ("start_at", "not-a-date"), ("end_at", "2030-13-02T10:00:00Z"),
            ("attendees_count", 0), ("attendees_count", -1),
            ("attendees_count", "invalid"), ("attendees_count", "2.5"),
        ):
            with self.subTest(field=field, value=value):
                response = self.search(**{field: value})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)

    def test_datetime_inputs_require_explicit_timezone(self):
        for field in ("start_at", "end_at"):
            with self.subTest(field=field):
                response = self.search(**{field: "2030-01-02T09:00:00"})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)

    def test_end_must_be_after_start(self):
        for end in (self.start, self.start - timedelta(minutes=1)):
            with self.subTest(end=end):
                response = self.search(end_at=end.isoformat())
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("end_at", response.data)

    def test_start_in_the_past_is_rejected(self):
        start = self.start - timedelta(days=2)
        response = self.search(start_at=start.isoformat(), end_at=(start + timedelta(hours=1)).isoformat())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_at", response.data)

    def test_duration_bounds_include_exact_limits(self):
        for duration, expected in (
            (timedelta(minutes=15) - timedelta(microseconds=1), 400),
            (timedelta(minutes=15), 200),
            (timedelta(minutes=180), 200),
            (timedelta(minutes=180) + timedelta(microseconds=1), 400),
        ):
            with self.subTest(duration=duration):
                self.assertEqual(self.search(end_at=(self.start + duration).isoformat()).status_code, expected)

    @override_settings(MIN_RESERVATION_MINUTES=30, MAX_RESERVATION_MINUTES=60)
    def test_duration_validation_uses_configured_settings(self):
        for minutes, expected in ((29, 400), (30, 200), (60, 200), (61, 400)):
            with self.subTest(minutes=minutes):
                response = self.search(end_at=(self.start + timedelta(minutes=minutes)).isoformat())
                self.assertEqual(response.status_code, expected)

    def test_working_hour_boundaries_in_tehran(self):
        for start_hour, start_minute, end_hour, end_minute, expected in (
            (8, 0, 8, 15, 200), (17, 45, 18, 0, 200),
            (7, 59, 8, 29, 400), (17, 45, 18, 1, 400), (18, 0, 18, 15, 400),
        ):
            with self.subTest(start=(start_hour, start_minute), end=(end_hour, end_minute)):
                response = self.search(
                    start_at=self.start.replace(hour=start_hour, minute=start_minute).isoformat(),
                    end_at=self.end.replace(hour=end_hour, minute=end_minute).isoformat(),
                )
                self.assertEqual(response.status_code, expected)

    def test_cross_company_date_interval_is_rejected(self):
        start = self.start.replace(hour=23, minute=50)
        response = self.search(start_at=start.isoformat(), end_at=(start + timedelta(minutes=20)).isoformat())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_at", response.data)

    def test_utc_and_other_offsets_describing_same_instants_return_same_rooms(self):
        expected = self.search().data
        for tz in (UTC, ZoneInfo("America/New_York")):
            with self.subTest(timezone=tz):
                response = self.search(
                    start_at=self.start.astimezone(tz).isoformat(),
                    end_at=self.end.astimezone(tz).isoformat(),
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data, expected)
        response = self.search(start_at="2030-01-02T05:30:00Z", end_at="2030-01-02T06:30:00Z")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_input_offset_does_not_override_company_working_hours(self):
        # 17:00–18:00 UTC is 20:30–21:30 in Tehran.
        response = self.search(start_at="2030-01-02T17:00:00Z", end_at="2030-01-02T18:00:00Z")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

    def test_non_conflicting_reservation_does_not_hide_the_room(self):
        for room in (self.free, self.busy):
            Reservation.objects.create(
                room=room, user=self.other, start_at=self.start + timedelta(hours=2),
                end_at=self.end + timedelta(hours=2), attendees_count=2,
            )
        response = self.search()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.free.pk, {room["id"] for room in response.data})
        self.assertNotIn(self.busy.pk, {room["id"] for room in response.data})

    def test_friday_is_allowed(self):
        start = self.start.replace(day=4)  # Friday.
        self.assertEqual(start.weekday(), 4)
        response = self.search(start_at=start.isoformat(), end_at=(start + timedelta(hours=1)).isoformat())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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


class SharedWindowValidationTests(SimpleTestCase):
    def test_shared_validator_rejects_naive_datetimes(self):
        start = datetime(2030, 1, 2, 9, tzinfo=COMPANY_TIMEZONE)
        for first, last, field in (
            (start.replace(tzinfo=None), start + timedelta(hours=1), "start_at"),
            (start, (start + timedelta(hours=1)).replace(tzinfo=None), "end_at"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError) as error:
                    validate_reservation_window(first, last)
                self.assertIn(field, error.exception.message_dict)

    def test_duration_uses_elapsed_time_across_foreign_timezone_dst_change(self):
        zone = ZoneInfo("America/New_York")
        start = datetime(2030, 3, 10, 1, 45, tzinfo=zone)
        end = datetime(2030, 3, 10, 3, 15, tzinfo=zone)
        with override_settings(MIN_RESERVATION_MINUTES=30, MAX_RESERVATION_MINUTES=30):
            with patch("reservations.validators.timezone.now", return_value=NOW):
                with timezone.override(zone):
                    validate_reservation_window(start, end)
