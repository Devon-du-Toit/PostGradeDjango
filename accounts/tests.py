from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


User = get_user_model()


class RegistrationTests(APITestCase):

    def test_register_user(self):
        data = {
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "TestPassword123!",
        }

        response = self.client.post(
            reverse("register"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 1)

        user = User.objects.get(email="test@example.com")

        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "User")
        self.assertTrue(user.check_password("TestPassword123!"))

    def test_password_is_not_returned_after_registration(self):
        data = {
            "email": "test@example.com",
            "password": "TestPassword123!",
        }

        response = self.client.post(
            reverse("register"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", response.data)

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            email="test@example.com",
            password="TestPassword123!",
        )

        data = {
            "email": "test@example.com",
            "password": "AnotherPassword123!",
        }

        response = self.client.post(
            reverse("register"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_short_password_is_rejected(self):
        data = {
            "email": "test@example.com",
            "password": "short",
        }

        response = self.client.post(
            reverse("register"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AuthenticationTests(APITestCase):

    def setUp(self):
        self.email = "test@example.com"
        self.password = "TestPassword123!"

        self.user = User.objects.create_user(
            email=self.email,
            first_name="Test",
            last_name="User",
            password=self.password,
        )

    def test_login_returns_tokens(self):
        data = {
            "email": self.email,
            "password": self.password,
        }

        response = self.client.post(
            reverse("login"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_invalid_password_is_rejected(self):
        data = {
            "email": self.email,
            "password": "WrongPassword123!",
        }

        response = self.client.post(
            reverse("login"),
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse("current_user"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_can_access_me(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": self.email,
                "password": self.password,
            },
            format="json",
        )

        access_token = login_response.data["access"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )

        response = self.client.get(reverse("current_user"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.email)
        self.assertEqual(response.data["first_name"], "Test")
        self.assertEqual(response.data["last_name"], "User")
        self.assertEqual(response.data["role"], User.Role.LECTURER)

    def test_refresh_token_returns_new_access_token(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": self.email,
                "password": self.password,
            },
            format="json",
        )

        refresh_token = login_response.data["refresh"]

        response = self.client.post(
            reverse("token_refresh"),
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

class UserManagerTests(APITestCase):

    def test_user_can_be_created_with_email(self):
        user = User.objects.create_user(
            email="another@example.com",
            password="TestPassword123!",
        )

        self.assertEqual(user.email, "another@example.com")
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertTrue(user.check_password("TestPassword123!"))

    def test_email_is_normalized(self):
        user = User.objects.create_user(
            email="Another@EXAMPLE.COM",
            password="TestPassword123!",
        )

        self.assertEqual(user.email, "Another@example.com")