import hashlib
import json
import re
from datetime import UTC

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from reservations.models import Reservation, ReservationRequest, Room
from reservations.serializers import ReservationSerializer
from reservations.validators import validate_reservation_window


class ReservationConflict(APIException):
    status_code = 409
    default_detail = "The room is already reserved for this time interval."
    default_code = "reservation_conflict"


def create_reservation(*, user, idempotency_key, room, start_at, end_at, attendees_count):
    if not isinstance(idempotency_key, str) or not re.fullmatch(r"[!-~]{1,255}", idempotency_key):
        raise ValidationError({
            "Idempotency-Key": "Use 1–255 visible ASCII characters without spaces."
        })

    for field, value in (("start_at", start_at), ("end_at", end_at)):
        if timezone.is_naive(value):
            raise ValidationError({field: "Include a timezone offset or Z."})

    payload = {
        "room": room,
        "start_at": start_at.astimezone(UTC).isoformat(),
        "end_at": end_at.astimezone(UTC).isoformat(),
        "attendees_count": attendees_count,
    }
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    try:
        with transaction.atomic():
            # The unique user/key claim waits for an identical in-flight key,
            # including when the two requests target different rooms.
            record, created = ReservationRequest.objects.get_or_create(
                user=user, key=idempotency_key, defaults={"request_hash": request_hash}
            )
            if not created:
                if record.request_hash != request_hash:
                    raise ReservationConflict(
                        "This Idempotency-Key was already used with different reservation data."
                    )
                if record.response_body is None:
                    raise RuntimeError("Incomplete reservation request record.")
                return record.response_body

            try:
                locked_room = Room.objects.select_for_update().get(pk=room)
            except Room.DoesNotExist as exc:
                raise NotFound("Room not found.") from exc

            # Recheck time after waiting for the room lock. Replays above must
            # still work after the start time has passed or the room has changed.
            try:
                validate_reservation_window(start_at, end_at)
            except DjangoValidationError as exc:
                raise ValidationError(exc.message_dict) from exc
            if attendees_count <= 0:
                raise ValidationError({"attendees_count": "Must be positive."})
            if not locked_room.is_active:
                raise ValidationError({"room": "This room is inactive."})
            if locked_room.capacity < attendees_count:
                raise ValidationError({"attendees_count": "The room has insufficient capacity."})

            if Reservation.objects.filter(
                room=locked_room,
                status=Reservation.Status.CONFIRMED,
                start_at__lt=end_at,
                end_at__gt=start_at,
            ).exists():
                raise ReservationConflict()

            reservation = Reservation.objects.create(
                room=locked_room, user=user, start_at=start_at, end_at=end_at,
                attendees_count=attendees_count,
            )
            record.reservation = reservation
            record.response_body = dict(ReservationSerializer(reservation).data)
            record.save(update_fields=["reservation", "response_body"])
            return record.response_body
    except IntegrityError as exc:
        # A write that bypasses the room-locking service is still protected by
        # PostgreSQL. Translate only this named constraint, outside atomic().
        if getattr(exc.__cause__, "diag", None) is not None:
            if exc.__cause__.diag.constraint_name == "reservation_no_overlap":
                raise ReservationConflict() from exc
        raise
