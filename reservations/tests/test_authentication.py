from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


class AuthenticationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "test-only-employee-password"
        cls.user = get_user_model().objects.create_user(
            username="employee", password=cls.password
        )
        cls.inactive_user = get_user_model().objects.create_user(
            username="inactive", password=cls.password, is_active=False
        )

    def test_valid_credentials_issue_a_token(self):
        response = self.client.post(
            reverse("auth-token"),
            {"username": self.user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"token": Token.objects.get(user=self.user).key})

    def test_invalid_or_missing_credentials_do_not_issue_a_token(self):
        for credentials in (
            {"username": self.user.username, "password": "wrong-password"},
            {"username": "unknown", "password": self.password},
            {"username": self.inactive_user.username, "password": self.password},
            {"username": self.user.username},
            {},
        ):
            with self.subTest(fields=tuple(credentials)):
                response = self.client.post(reverse("auth-token"), credentials, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertNotIn("token", response.data)
        self.assertFalse(Token.objects.exists())

    def test_inactive_user_token_cannot_access_the_api(self):
        token = Token.objects.create(user=self.inactive_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get(reverse("room-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
