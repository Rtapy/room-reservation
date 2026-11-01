from rest_framework import mixins, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from reservations.models import Reservation, Room
from reservations.permissions import IsReservationOwnerOrStaff, IsStaffOrReadOnly
from reservations.selectors import get_available_rooms
from reservations.serializers import AvailabilityQuerySerializer, ReservationSerializer, RoomSerializer


class ObtainTokenView(ObtainAuthToken):
    authentication_classes = ()
    permission_classes = (AllowAny,)


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


class ReservationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReservationSerializer
    permission_classes = (IsReservationOwnerOrStaff,)

    def get_queryset(self):
        queryset = Reservation.objects.select_related("room", "user")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)
