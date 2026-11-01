from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reservations.models import Reservation, Room
from reservations.permissions import IsReservationOwnerOrStaff


class AccessControlTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = get_user_model().objects.create_user(username="employee")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        cls.tokens = {
            user.pk: Token.objects.create(user=user).key
            for user in (cls.employee, cls.other, cls.staff)
        }
        cls.room = Room.objects.create(name="Room A", capacity=6)
        cls.inactive_room = Room.objects.create(name="Room B", capacity=3, is_active=False)
        start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
        cls.own_reservation = Reservation.objects.create(
            room=cls.room, user=cls.employee, start_at=start,
            end_at=start + timedelta(hours=1), attendees_count=2,
        )
        cls.other_reservation = Reservation.objects.create(
            room=cls.room, user=cls.other, start_at=start + timedelta(hours=1),
            end_at=start + timedelta(hours=2), attendees_count=2,
        )
        cls.cancelled_reservation = Reservation.objects.create(
            room=cls.room, user=cls.employee, start_at=start,
            end_at=start + timedelta(hours=1), attendees_count=2,
            status=Reservation.Status.CANCELLED, cancelled_at=start - timedelta(days=1),
        )

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[user.pk]}")

    def test_missing_or_invalid_token_cannot_read_resources(self):
        for authorization in (None, "Token invalid-token", "Token", "Bearer wrong-token"):
            self.client.credentials(
                **({"HTTP_AUTHORIZATION": authorization} if authorization else {})
            )
            for url in (
                reverse("room-list"), reverse("reservation-list"),
                reverse("reservation-detail", args=[self.own_reservation.pk]),
            ):
                with self.subTest(authorization=authorization, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                    self.assertEqual(response["WWW-Authenticate"], "Token")

    def test_anonymous_user_cannot_write_rooms(self):
        response = self.client.post(
            reverse("room-list"), {"name": "Unauthorized", "capacity": 4}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response = self.client.patch(
            reverse("room-detail", args=[self.room.pk]), {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Room.objects.count(), 2)
        self.room.refresh_from_db()
        self.assertTrue(self.room.is_active)

    def test_employee_can_list_rooms_including_inactive_rooms(self):
        self.authenticate(self.employee)
        response = self.client.get(reverse("room-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({room["id"] for room in response.data}, {self.room.pk, self.inactive_room.pk})

    def test_employee_cannot_create_a_room(self):
        self.authenticate(self.employee)
        response = self.client.post(
            reverse("room-list"), {"name": "Unauthorized", "capacity": 4}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Room.objects.count(), 2)

    def test_employee_cannot_edit_or_deactivate_a_room(self):
        self.authenticate(self.employee)
        response = self.client.patch(
            reverse("room-detail", args=[self.room.pk]),
            {"name": "Changed", "capacity": 1, "is_active": False}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.room.refresh_from_db()
        self.assertEqual((self.room.name, self.room.capacity, self.room.is_active), ("Room A", 6, True))

    def test_staff_can_create_a_room(self):
        self.authenticate(self.staff)
        response = self.client.post(
            reverse("room-list"), {"name": "New room", "capacity": 4}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Room.objects.filter(pk=response.data["id"], capacity=4).exists())

    def test_staff_can_edit_and_deactivate_a_room(self):
        self.authenticate(self.staff)
        response = self.client.patch(
            reverse("room-detail", args=[self.room.pk]),
            {"name": "Updated", "capacity": 8, "is_active": False}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.room.refresh_from_db()
        self.assertEqual((self.room.name, self.room.capacity, self.room.is_active), ("Updated", 8, False))

    def test_room_api_rejects_invalid_capacity_and_duplicate_names(self):
        self.authenticate(self.staff)
        for capacity in (0, -1):
            with self.subTest(capacity=capacity):
                response = self.client.post(
                    reverse("room-list"), {"name": "Invalid", "capacity": capacity}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(
            reverse("room-list"), {"name": self.room.name, "capacity": 4}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Room.objects.count(), 2)

    def test_employee_list_contains_only_their_reservations(self):
        self.authenticate(self.employee)
        response = self.client.get(reverse("reservation-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {reservation["id"] for reservation in response.data},
            {self.own_reservation.pk, self.cancelled_reservation.pk},
        )

    def test_query_parameter_cannot_expose_another_users_reservations(self):
        self.authenticate(self.employee)
        response = self.client.get(reverse("reservation-list"), {"user": self.other.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {reservation["user"] for reservation in response.data}, {self.employee.pk}
        )

    def test_employee_can_read_their_reservation(self):
        self.authenticate(self.employee)
        response = self.client.get(reverse("reservation-detail", args=[self.own_reservation.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"], self.employee.pk)
        self.assertEqual(response.data["room"], self.room.pk)

    def test_other_users_reservation_and_missing_id_both_return_404(self):
        self.authenticate(self.employee)
        for pk in (self.other_reservation.pk, self.other_reservation.pk + 1000):
            with self.subTest(pk=pk):
                response = self.client.get(reverse("reservation-detail", args=[pk]))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_list_and_read_everyones_reservations(self):
        self.authenticate(self.staff)
        response = self.client.get(reverse("reservation-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        response = self.client.get(reverse("reservation-detail", args=[self.other_reservation.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"], self.other.pk)

    def test_reservation_read_endpoints_do_not_allow_direct_mutation(self):
        self.authenticate(self.employee)
        url = reverse("reservation-detail", args=[self.own_reservation.pk])
        response = self.client.patch(url, {"user": self.other.pk, "status": "cancelled"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.own_reservation.refresh_from_db()
        self.assertEqual(self.own_reservation.user_id, self.employee.pk)
        self.assertEqual(self.own_reservation.status, Reservation.Status.CONFIRMED)

    def test_object_permission_allows_only_owner_or_staff(self):
        permission = IsReservationOwnerOrStaff()
        # This permission will also protect the cancellation action in stage 6.
        for method in ("GET", "POST"):
            for user, expected in (
                (self.employee, True), (self.staff, True),
                (self.other, False), (AnonymousUser(), False),
            ):
                with self.subTest(method=method, user=user.username):
                    request = SimpleNamespace(user=user, method=method)
                    self.assertEqual(
                        permission.has_object_permission(request, None, self.own_reservation),
                        expected,
                    )
