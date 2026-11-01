from django.urls import path
from rest_framework.routers import SimpleRouter

from reservations.views import ObtainTokenView, ReservationViewSet, RoomViewSet

router = SimpleRouter()
router.register("rooms", RoomViewSet, basename="room")
router.register("reservations", ReservationViewSet, basename="reservation")

urlpatterns = [
    path("auth/token/", ObtainTokenView.as_view(), name="auth-token"),
    *router.urls,
]
