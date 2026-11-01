from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from reservations.validators import validate_reservation_window


NOW = datetime(2030, 1, 1, tzinfo=UTC)
START = datetime(2030, 1, 4, 9, tzinfo=ZoneInfo("Asia/Tehran"))


@override_settings(MIN_RESERVATION_MINUTES=30, MAX_RESERVATION_MINUTES=60)
class ReservationWindowTests(SimpleTestCase):
    """One boundary matrix for the validator shared by search and creation."""

    def setUp(self):
        clock = patch("reservations.validators.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def test_time_order_and_past_start_are_rejected(self):
        for start, end, field in (
            (START, START, "end_at"),
            (START, START - timedelta(minutes=1), "end_at"),
            (START - timedelta(days=4), START - timedelta(days=4) + timedelta(hours=1), "start_at"),
        ):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValidationError) as error:
                    validate_reservation_window(start, end)
                self.assertIn(field, error.exception.message_dict)

    def test_duration_boundaries_follow_configured_settings(self):
        for duration, valid in (
            (timedelta(minutes=30) - timedelta(microseconds=1), False),
            (timedelta(minutes=30), True),
            (timedelta(minutes=60), True),
            (timedelta(minutes=60) + timedelta(microseconds=1), False),
        ):
            with self.subTest(duration=duration):
                if valid:
                    validate_reservation_window(START, START + duration)
                else:
                    with self.assertRaises(ValidationError) as error:
                        validate_reservation_window(START, START + duration)
                    self.assertIn("end_at", error.exception.message_dict)

    @override_settings(MIN_RESERVATION_MINUTES=15, MAX_RESERVATION_MINUTES=180)
    def test_company_date_and_working_hours(self):
        for start, end, valid in (
            (START.replace(hour=8), START.replace(hour=8, minute=15), True),
            (START.replace(hour=17, minute=45), START.replace(hour=18), True),
            (START.replace(hour=7, minute=59), START.replace(hour=8, minute=29), False),
            (START.replace(hour=17, minute=45), START.replace(hour=18, minute=1), False),
            (START.replace(hour=18), START.replace(hour=18, minute=15), False),
            (START.replace(hour=23, minute=50), (START + timedelta(days=1)).replace(hour=0, minute=10), False),
        ):
            with self.subTest(start=start, end=end):
                # Validate absolute instants; business hours still use Tehran.
                start, end = start.astimezone(UTC), end.astimezone(UTC)
                if valid:
                    validate_reservation_window(start, end)
                else:
                    with self.assertRaises(ValidationError):
                        validate_reservation_window(start, end)
