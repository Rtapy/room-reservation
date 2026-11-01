from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reservations.models import Reservation, Room


class ReservationCancellationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="owner")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        cls.tokens = {
            user.pk: Token.objects.create(user=user).key
            for user in (cls.owner, cls.other, cls.staff)
        }
        room = Room.objects.create(name="Meeting room", capacity=4)
        start = datetime(2030, 1, 2, 6, tzinfo=UTC)
        cls.reservation = Reservation.objects.create(
            room=room, user=cls.owner, start_at=start,
            end_at=start + timedelta(hours=1), attendees_count=3,
        )

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tokens[user.pk]}")

    def cancel(self, pk=None):
        return self.client.post(reverse(
            "reservation-cancel", args=[self.reservation.pk if pk is None else pk]
        ))

    def test_owner_cancels_without_deleting_reservation_history(self):
        self.authenticate(self.owner)
        before = (
            self.reservation.room_id, self.reservation.user_id,
            self.reservation.start_at, self.reservation.end_at,
            self.reservation.attendees_count, self.reservation.created_at,
        )
        response = self.cancel()
        self.assertEqual(response.status_code, 200)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CANCELLED)
        self.assertIsNotNone(self.reservation.cancelled_at)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertIsNotNone(response.data["cancelled_at"])
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(before, (
            self.reservation.room_id, self.reservation.user_id,
            self.reservation.start_at, self.reservation.end_at,
            self.reservation.attendees_count, self.reservation.created_at,
        ))
        detail = self.client.get(reverse("reservation-detail", args=[self.reservation.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], "cancelled")

    def test_staff_can_cancel_another_users_reservation(self):
        self.authenticate(self.staff)
        response = self.cancel()
        self.assertEqual(response.status_code, 200)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CANCELLED)
        self.assertEqual(self.reservation.user_id, self.owner.pk)

    def test_other_user_and_missing_reservation_return_404_without_changes(self):
        self.authenticate(self.other)
        for pk in (self.reservation.pk, self.reservation.pk + 1000):
            with self.subTest(pk=pk):
                self.assertEqual(self.cancel(pk=pk).status_code, 404)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CONFIRMED)
        self.assertIsNone(self.reservation.cancelled_at)

    def test_unauthenticated_user_cannot_cancel(self):
        self.assertEqual(self.cancel().status_code, 401)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CONFIRMED)
        self.assertIsNone(self.reservation.cancelled_at)

    def test_repeated_cancellation_preserves_first_timestamp_and_response(self):
        self.authenticate(self.owner)
        first_time = datetime(2030, 1, 1, tzinfo=UTC)
        with patch("reservations.services.timezone.now", return_value=first_time):
            first = self.cancel()
        with patch("reservations.services.timezone.now", return_value=first_time + timedelta(hours=1)):
            second = self.cancel()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.cancelled_at, first_time)
