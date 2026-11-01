from datetime import UTC, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_reservation_window(start_at, end_at):
    """Validate the shared time rules for availability and reservation creation."""
    for field, value in (("start_at", start_at), ("end_at", end_at)):
        if timezone.is_naive(value):
            raise ValidationError({field: "Include a timezone offset or Z."})

    start_at = start_at.astimezone(UTC)
    end_at = end_at.astimezone(UTC)
    if end_at <= start_at:
        raise ValidationError({"end_at": "End time must be after start time."})
    if start_at < timezone.now():
        raise ValidationError({"start_at": "Reservations in the past are not allowed."})

    duration = end_at - start_at
    if not (
        timedelta(minutes=settings.MIN_RESERVATION_MINUTES)
        <= duration
        <= timedelta(minutes=settings.MAX_RESERVATION_MINUTES)
    ):
        raise ValidationError({
            "end_at": (
                f"Duration must be between {settings.MIN_RESERVATION_MINUTES} "
                f"and {settings.MAX_RESERVATION_MINUTES} minutes."
            )
        })

    company_timezone = timezone.get_default_timezone()
    local_start = timezone.localtime(start_at, company_timezone)
    local_end = timezone.localtime(end_at, company_timezone)
    if local_start.date() != local_end.date():
        raise ValidationError({"end_at": "The session must start and end on the same company date."})
    if local_start.time() < time(8) or local_end.time() > time(18):
        raise ValidationError({"non_field_errors": "The entire session must be within 08:00–18:00 Asia/Tehran."})
