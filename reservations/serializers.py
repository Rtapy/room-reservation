from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from reservations.models import Reservation, Room
from reservations.validators import validate_reservation_window


class AwareDateTimeField(serializers.DateTimeField):
    default_error_messages = {"timezone_required": "Include a timezone offset or Z."}

    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            self.fail("timezone_required")
        return super().enforce_timezone(value)


class AvailabilityQuerySerializer(serializers.Serializer):
    start_at = AwareDateTimeField()
    end_at = AwareDateTimeField()
    attendees_count = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        try:
            validate_reservation_window(attrs["start_at"], attrs["end_at"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ("id", "name", "capacity", "is_active")
        read_only_fields = ("id",)


class ReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = (
            "id",
            "room",
            "user",
            "start_at",
            "end_at",
            "attendees_count",
            "status",
            "created_at",
            "cancelled_at",
        )
        read_only_fields = fields
