from rest_framework import serializers

from reservations.models import Reservation, Room


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
