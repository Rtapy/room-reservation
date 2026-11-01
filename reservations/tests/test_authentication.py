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

    def test_repeated_login_returns_the_same_token(self):
        credentials = {"username": self.user.username, "password": self.password}
        first = self.client.post(reverse("auth-token"), credentials, format="json")
        second = self.client.post(reverse("auth-token"), credentials, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Token.objects.filter(user=self.user).count(), 1)

    def test_invalid_or_missing_credentials_do_not_issue_a_token(self):
        for credentials in (
            {"username": self.user.username, "password": "wrong-password"},
            {"username": "unknown", "password": self.password},
            {"username": self.user.username},
            {},
        ):
            with self.subTest(fields=tuple(credentials)):
                response = self.client.post(reverse("auth-token"), credentials, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertNotIn("token", response.data)
        self.assertFalse(Token.objects.exists())

    def test_inactive_user_cannot_obtain_a_token(self):
        response = self.client.post(
            reverse("auth-token"),
            {"username": self.inactive_user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Token.objects.filter(user=self.inactive_user).exists())

    def test_login_does_not_require_a_valid_existing_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token stale-token")
        response = self.client.post(
            reverse("auth-token"),
            {"username": self.user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["token"], Token.objects.get(user=self.user).key)

    def test_inactive_user_token_cannot_access_the_api(self):
        token = Token.objects.create(user=self.inactive_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get(reverse("room-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_session_login_does_not_replace_token_authentication(self):
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(reverse("room-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
