from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class Room(models.Model):
    name = models.CharField(max_length=100, unique=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gt=0),
                name="room_capacity_positive",
            ),
        ]

    def __str__(self):
        return self.name


class Reservation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="reservations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    attendees_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(attendees_count__gt=0),
                name="reservation_attendees_positive",
            ),
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="reservation_time_order",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="confirmed", cancelled_at__isnull=True)
                    | Q(status="cancelled", cancelled_at__isnull=False)
                ),
                name="reservation_valid_state",
            ),
            ExclusionConstraint(
                name="reservation_no_overlap",
                expressions=[
                    ("room", RangeOperators.EQUAL),
                    (
                        models.Func(
                            "start_at",
                            "end_at",
                            RangeBoundary(),
                            function="TSTZRANGE",
                            output_field=DateTimeRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status="confirmed"),
            ),
        ]

    def __str__(self):
        return f"Room {self.room_id}: {self.start_at} - {self.end_at}"
