from drf_spectacular.utils import extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from reservations.models import Reservation, Room
from reservations.permissions import IsReservationOwnerOrStaff, IsStaffOrReadOnly
from reservations.schema import RESERVATION_SCHEMA, ROOM_SCHEMA, TOKEN_SCHEMA
from reservations.selectors import get_available_rooms
from reservations.serializers import (
    AvailabilityQuerySerializer, ReservationCreateSerializer, ReservationSerializer, RoomSerializer,
)
from reservations.services import cancel_reservation, create_reservation


@extend_schema_view(**TOKEN_SCHEMA)
class ObtainTokenView(ObtainAuthToken):
    authentication_classes = ()
    permission_classes = (AllowAny,)


@extend_schema_view(**ROOM_SCHEMA)
class RoomViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_classes = (IsStaffOrReadOnly,)
    http_method_names = ("get", "post", "patch", "head", "options")

    @action(detail=False, methods=["get"])
    def available(self, request):
        params = AvailabilityQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        rooms = get_available_rooms(**params.validated_data)
        return Response(self.get_serializer(rooms, many=True).data)


@extend_schema_view(**RESERVATION_SCHEMA)
class ReservationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ReservationSerializer
    permission_classes = (IsReservationOwnerOrStaff,)

    def create(self, request):
        params = ReservationCreateSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        response_body = create_reservation(
            user=request.user,
            idempotency_key=request.headers.get("Idempotency-Key"),
            **params.validated_data,
        )
        return Response(response_body, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        reservation = self.get_object()
        reservation = cancel_reservation(reservation=reservation)
        return Response(self.get_serializer(reservation).data)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Reservation.objects.none()
        queryset = Reservation.objects.select_related("room", "user")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)
