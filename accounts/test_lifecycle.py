from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AccountLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="synthetic@example.invalid", password="ExamplePassword!42"
        )
        self.client = APIClient()
        caches["throttle"].clear()

    def login(self):
        return self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": "ExamplePassword!42"},
            format="json",
        )

    def test_signup_is_always_open_and_ignores_privilege_fields(self):
        payload = {
            "email": "new@example.invalid",
            "password": "ExamplePassword!42",
            "role": "ADMIN",
            "is_staff": True,
            "is_superuser": True,
            "is_active": False,
        }
        with override_settings(DEBUG=False, ALLOW_REGISTRATION=False):
            self.assertEqual(
                self.client.get("/api/auth/registration-policy/").data[
                    "registration_open"
                ],
                True,
            )
            self.assertEqual(
                self.client.post("/api/auth/register/", payload).status_code, 201
            )
        user = User.objects.get(email=payload["email"])
        self.assertEqual(user.role, "LECTURER")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)

    @override_settings(LOGIN_THROTTLE_RATE="2/min")
    def test_login_throttle_ignores_spoofed_forwarding_headers(self):
        for ip in ("1.2.3.4", "5.6.7.8"):
            response = self.client.post(
                "/api/auth/login/",
                {"email": self.user.email, "password": "wrong"},
                HTTP_X_FORWARDED_FOR=ip,
            )
            self.assertEqual(response.status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        # A different web client sees the same shared cache entries.
        self.assertEqual(APIClient().post("/api/auth/login/", {}).status_code, 429)

    @override_settings(REGISTER_THROTTLE_RATE="1/hour")
    def test_registration_is_throttled(self):
        self.assertEqual(self.client.post("/api/auth/register/", {}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register/", {}).status_code, 429)

    def test_rotation_and_logout_revoke_refresh_but_access_expires_normally(self):
        tokens = self.login().data
        old = tokens["refresh"]
        response = self.client.post("/api/auth/refresh/", {"refresh": old})
        self.assertEqual(response.status_code, 200)
        rotated = response.data["refresh"]
        self.assertNotEqual(old, rotated)
        self.assertEqual(
            self.client.post("/api/auth/refresh/", {"refresh": old}).status_code, 401
        )
        # Logout works even when the access header has expired/invalid bytes.
        self.client.credentials(HTTP_AUTHORIZATION="Bearer expired")
        self.assertEqual(
            self.client.post("/api/auth/logout/", {"refresh": rotated}).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/auth/refresh/", {"refresh": rotated}).status_code,
            401,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        token = RefreshToken(tokens["refresh"], verify=False)
        self.assertEqual(token["exp"] - token["iat"], 86400)
        self.assertEqual(token.access_token["exp"] - token.access_token["iat"], 300)

    def test_password_change_revokes_access_and_refresh(self):
        tokens = self.login().data
        self.user.set_password("DifferentPassword!42")
        self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", {"refresh": tokens["refresh"]}
            ).status_code,
            401,
        )

    def test_inactive_and_deleted_accounts_cannot_refresh(self):
        tokens = self.login().data
        self.user.is_active = False
        self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", {"refresh": tokens["refresh"]}
            ).status_code,
            401,
        )
        self.user.delete()
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", {"refresh": tokens["refresh"]}
            ).status_code,
            401,
        )
        self.assertEqual(self.login().status_code, 401)

    @override_settings(REFRESH_THROTTLE_RATE="1/min", LOGOUT_THROTTLE_RATE="1/min")
    def test_refresh_and_logout_have_independent_throttles(self):
        for path in ("refresh", "logout"):
            self.assertEqual(
                self.client.post(f"/api/auth/{path}/", {}).status_code, 400
            )
            response = self.client.post(f"/api/auth/{path}/", {})
            self.assertEqual(response.status_code, 429)
            self.assertIn("Retry-After", response)

    def test_signup_password_validation_uses_account_attributes(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": "stronglongname@example.invalid",
                "first_name": "StrongLongName",
                "password": "StrongLongName",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            User.objects.filter(email="stronglongname@example.invalid").exists()
        )

    def test_invalid_and_wrong_token_types_do_not_revoke_another_session(self):
        tokens = self.login().data
        for token in ("bad", tokens["access"]):
            self.assertEqual(
                self.client.post("/api/auth/logout/", {"refresh": token}).status_code,
                401,
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", {"refresh": tokens["refresh"]}
            ).status_code,
            200,
        )


class ConcurrentRotationTests(TransactionTestCase):
    def test_a_refresh_token_can_only_be_consumed_once(self):
        user = User.objects.create_user(
            email="concurrent@example.invalid", password="ExamplePassword!42"
        )
        token = str(RefreshToken.for_user(user))
        barrier = Barrier(2)

        def refresh():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return (
                    APIClient()
                    .post("/api/auth/refresh/", {"refresh": token})
                    .status_code
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: refresh(), range(2)))
        self.assertCountEqual(statuses, [200, 401])
