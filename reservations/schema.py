"""OpenAPI annotations for contracts that cannot be inferred from the views."""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.authtoken.serializers import AuthTokenSerializer

from reservations.serializers import (
    AvailabilityQuerySerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    RoomSerializer,
)

DETAIL_ERROR = inline_serializer("DetailError", {"detail": serializers.CharField()})
INVALID_INPUT = OpenApiResponse(
    response={
        "type": "object",
        "additionalProperties": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
    },
    description="Invalid input; errors are keyed by field name or non_field_errors.",
)
UNAUTHENTICATED = OpenApiResponse(DETAIL_ERROR, description="Missing or invalid token.")
STAFF_ONLY = OpenApiResponse(DETAIL_ERROR, description="Room management requires is_staff.")
NOT_FOUND = OpenApiResponse(DETAIL_ERROR, description="Not found or outside the user's access.")
TIME_RULES = (
    "Both datetimes require an offset or Z. The interval must be in the future, "
    "with start_at < end_at, entirely within 08:00–18:00 on the same Asia/Tehran date. "
    "Duration limits come from MIN_RESERVATION_MINUTES and MAX_RESERVATION_MINUTES. "
    "There is no weekday restriction. Adjacent intervals are allowed."
)

TOKEN_SCHEMA = {
    "post": extend_schema(
        tags=["Authentication"],
        summary="Obtain a token",
        description="Use an existing active user's credentials. Repeated login returns the same token.",
        request=AuthTokenSerializer,
        responses={
            200: inline_serializer("TokenResponse", {"token": serializers.CharField()}),
            400: INVALID_INPUT,
        },
        auth=[],
    ),
}

ROOM_SCHEMA = {
    "list": extend_schema(
        tags=["Rooms"],
        summary="List rooms",
        description="All rooms, including inactive ones, for any authenticated user. Returns a JSON array.",
        responses={200: RoomSerializer(many=True), 401: UNAUTHENTICATED},
    ),
    "create": extend_schema(
        tags=["Rooms"],
        summary="Create a room (staff)",
        description="Requires a unique name and positive capacity. is_active defaults to true.",
        responses={201: RoomSerializer, 400: INVALID_INPUT, 401: UNAUTHENTICATED, 403: STAFF_ONLY},
    ),
    "partial_update": extend_schema(
        tags=["Rooms"],
        summary="Edit or deactivate a room (staff)",
        description="Update name, capacity, or is_active. Existing reservations are retained.",
        responses={
            200: RoomSerializer, 400: INVALID_INPUT, 401: UNAUTHENTICATED,
            403: STAFF_ONLY, 404: NOT_FOUND,
        },
    ),
    "available": extend_schema(
        tags=["Rooms"],
        summary="Find available rooms",
        description=(
            "Active rooms with capacity >= attendees_count and no overlapping confirmed reservation. "
            "Cancelled reservations are ignored; no matches returns []. "
            "Search does not hold a room; creation checks availability again. " + TIME_RULES
        ),
        parameters=[AvailabilityQuerySerializer],
        responses={200: RoomSerializer(many=True), 400: INVALID_INPUT, 401: UNAUTHENTICATED},
    ),
}

RESERVATION_SCHEMA = {
    "list": extend_schema(
        tags=["Reservations"],
        summary="List reservations",
        description="Own reservations, including cancelled ones. Staff see all users' reservations. Returns a JSON array.",
        responses={200: ReservationSerializer(many=True), 401: UNAUTHENTICATED},
    ),
    "retrieve": extend_schema(
        tags=["Reservations"],
        summary="Read a reservation",
        description="Owner or staff only. Another employee's reservation returns 404.",
        responses={200: ReservationSerializer, 401: UNAUTHENTICATED, 404: NOT_FOUND},
    ),
    "create": extend_schema(
        tags=["Reservations"],
        summary="Create a reservation",
        description=(
            "The authenticated user is always the owner; initial status is confirmed. "
            "The room must be active and have enough capacity. " + TIME_RULES + "\n\n"
            "Idempotency-Key is scoped to the user. The same key and effective data replay the original "
            "201 response, including after cancellation, room changes, or the start time passing. "
            "Times are normalized to UTC for comparison. Different data for a successful key return 409. "
            "Failed requests consume no key; successful keys have no automatic expiry. "
            "Concurrent overlapping requests with different keys produce at most one reservation."
        ),
        request=ReservationCreateSerializer,
        parameters=[OpenApiParameter(
            name="Idempotency-Key",
            location=OpenApiParameter.HEADER,
            required=True,
            type={"type": "string", "minLength": 1, "maxLength": 255, "pattern": "^[!-~]{1,255}$"},
            description="Unique request key: 1–255 visible ASCII characters without spaces (for example, a UUID).",
        )],
        examples=[OpenApiExample(
            "Reservation request",
            value={
                "room": 1,
                "start_at": "2030-01-02T09:00:00+03:30",
                "end_at": "2030-01-02T10:00:00+03:30",
                "attendees_count": 3,
            },
            description="Use an existing room ID and a future interval within the configured duration limits.",
            request_only=True,
        )],
        responses={
            201: OpenApiResponse(ReservationSerializer, description="Created, or the original successful response replayed."),
            400: INVALID_INPUT,
            401: UNAUTHENTICATED,
            404: OpenApiResponse(DETAIL_ERROR, description="Room not found."),
            409: OpenApiResponse(DETAIL_ERROR, description="Overlapping reservation, or key reused with different effective data."),
        },
    ),
    "cancel": extend_schema(
        tags=["Reservations"],
        summary="Cancel a reservation",
        description=(
            "Owner or staff only. Soft cancellation retains the row and frees the interval. "
            "No request body or Idempotency-Key is needed. Repeating cancellation preserves the first "
            "cancelled_at timestamp and returns 200. Replaying the creation key still returns the original "
            "creation response and does not reactivate the reservation."
        ),
        request=None,
        responses={200: ReservationSerializer, 401: UNAUTHENTICATED, 404: NOT_FOUND},
    ),
}
