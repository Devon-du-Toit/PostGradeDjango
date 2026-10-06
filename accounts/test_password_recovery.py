from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import caches
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from accounts.models import PasswordResetRequest, User
from accounts.recovery import confirm_recovery


@override_settings(
    ALLOW_PASSWORD_RECOVERY=True,
    PASSWORD_RESET_FRONTEND_URL="https://trusted.example/reset-password",
    PASSWORD_RESET_THROTTLE_RATE="100/hour",
    PASSWORD_RESET_CONFIRM_THROTTLE_RATE="100/hour",
)
class PasswordRecoveryTests(TransactionTestCase):
    def setUp(self):
        caches["throttle"].clear()
        self.user = User.objects.create_user(
            email="recovery@example.com", password="OldSyntheticPassword923!"
        )
        self.client = APIClient()
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def confirm(self, **updates):
        payload = {
            "uid": self.uid,
            "token": self.token,
            "password": "NewSyntheticPassword742!",
        }
        payload.update(updates)
        return self.client.post("/api/auth/password-reset/confirm/", payload)

    def test_known_unknown_and_disabled_have_identical_response(self):
        known = self.client.post(
            "/api/auth/password-reset/", {"email": self.user.email}
        )
        unknown = self.client.post(
            "/api/auth/password-reset/", {"email": "absent@example.com"}
        )
        call_command("send_password_resets")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        disabled = self.client.post(
            "/api/auth/password-reset/", {"email": self.user.email}
        )
        self.assertEqual(
            (known.status_code, known.data), (unknown.status_code, unknown.data)
        )
        self.assertEqual(
            (known.status_code, known.data), (disabled.status_code, disabled.data)
        )
        self.assertEqual(known.status_code, 202)
        call_command("send_password_resets")
        self.assertEqual(len(mail.outbox), 1)

    def test_trusted_link_does_not_use_request_host_and_never_emails_password(self):
        self.client.post(
            "/api/auth/password-reset/",
            {"email": self.user.email},
            HTTP_HOST="evil.example",
        )
        call_command("send_password_resets")
        self.assertEqual(len(mail.outbox), 1)
        link = next(
            line
            for line in mail.outbox[0].body.splitlines()
            if line.startswith("https://")
        )
        self.assertEqual(urlsplit(link).netloc, "trusted.example")
        self.assertEqual(urlsplit(link).query, "")
        query = parse_qs(urlsplit(link).fragment)
        self.assertEqual(query["uid"], [self.uid])
        self.assertTrue(
            default_token_generator.check_token(self.user, query["token"][0])
        )
        self.assertNotIn("OldSyntheticPassword923!", mail.outbox[0].body)

    def test_success_single_use_and_sessions_revoked(self):
        pair = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": "OldSyntheticPassword923!"},
        ).data
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.confirm().status_code, 400)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + pair["access"])
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/refresh/", {"refresh": pair["refresh"]}
            ).status_code,
            401,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSyntheticPassword742!"))

    def test_expired_token(self):
        future = default_token_generator._now() + timedelta(seconds=3601)
        with patch.object(default_token_generator, "_now", return_value=future):
            self.assertEqual(self.confirm().status_code, 400)

    def test_invalid_unknown_and_disabled_links(self):
        self.assertEqual(self.confirm(uid="bad").status_code, 400)
        self.assertEqual(self.confirm(token="invalid").status_code, 400)
        self.assertEqual(
            self.confirm(uid=urlsafe_base64_encode(b"99999999")).status_code, 400
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.confirm().status_code, 400)

    def test_password_validation_and_no_token_consumption_on_failure(self):
        result = self.confirm(password="123")
        self.assertEqual(result.status_code, 400)
        self.assertIn("password", result.data)
        self.assertEqual(self.confirm().status_code, 200)

    def test_smtp_failure_response_safe(self):
        with patch(
            "accounts.recovery.send_mail",
            side_effect=RuntimeError("private SMTP error"),
        ):
            result = self.client.post(
                "/api/auth/password-reset/", {"email": self.user.email}
            )
            call_command("send_password_resets")
        self.assertEqual(result.status_code, 202)
        self.assertEqual(PasswordResetRequest.objects.get().attempts, 1)
        self.assertNotIn("private", str(result.data))

    @override_settings(PASSWORD_RESET_THROTTLE_RATE="1/hour")
    def test_request_rate_limit_for_unknown_accounts(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/password-reset/", {"email": "unknown@example.com"}
            ).status_code,
            202,
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/password-reset/", {"email": "another@example.com"}
            ).status_code,
            429,
        )

    @override_settings(PASSWORD_RESET_CONFIRM_THROTTLE_RATE="1/hour")
    def test_confirm_rate_limit(self):
        self.confirm(token="invalid")
        self.assertEqual(self.confirm(token="invalid").status_code, 429)

    @override_settings(
        DEBUG=False, PASSWORD_RESET_FRONTEND_URL="http://unsafe.example/reset-password"
    )
    def test_untrusted_production_url_fails_closed(self):
        result = self.client.get("/api/auth/registration-policy/")
        self.assertFalse(result.data["password_recovery_available"])
        self.assertEqual(
            self.client.post(
                "/api/auth/password-reset/", {"email": self.user.email}
            ).status_code,
            403,
        )
        self.assertEqual(self.confirm().status_code, 403)

    @override_settings(ALLOW_PASSWORD_RECOVERY=False)
    def test_disabled_policy(self):
        self.assertFalse(
            self.client.get("/api/auth/registration-policy/").data[
                "password_recovery_available"
            ]
        )

    def test_ambiguous_case_alias_does_not_reset_arbitrary_account(self):
        User.objects.create_user(
            email="RECOVERY@example.com", password="AnotherSyntheticPassword487!"
        )
        self.client.post("/api/auth/password-reset/", {"email": self.user.email})
        call_command("send_password_resets")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_malformed_configuration_is_unavailable(self):
        for url in [
            "https://:443/reset",
            "https://host:bad/reset",
            "https://[bad/reset",
        ]:
            with override_settings(PASSWORD_RESET_FRONTEND_URL=url):
                self.assertFalse(
                    self.client.get("/api/auth/registration-policy/").data[
                        "password_recovery_available"
                    ]
                )

    def test_malformed_request_bodies_are_validation_errors(self):
        for payload in [[], None, {"email": []}, {"email": 123}]:
            response = self.client.post(
                "/api/auth/password-reset/", payload, format="json"
            )
            self.assertEqual(response.status_code, 400)
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_queued_request_before_successful_reset_cannot_send_fresh_token(self):
        self.client.post("/api/auth/password-reset/", {"email": self.user.email})
        self.assertEqual(self.confirm().status_code, 200)
        call_command("send_password_resets")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_expired_unknown_jobs_are_purged_even_if_recovery_disabled(self):
        item = PasswordResetRequest.objects.create(email="unknown@example.com")
        PasswordResetRequest.objects.filter(pk=item.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )
        with override_settings(ALLOW_PASSWORD_RECOVERY=False):
            call_command("send_password_resets")
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_delivery_backoff_and_three_attempt_retention_bound(self):
        self.client.post("/api/auth/password-reset/", {"email": self.user.email})
        with patch(
            "accounts.recovery.send_mail", side_effect=RuntimeError("private error")
        ) as sender:
            for attempt in range(3):
                PasswordResetRequest.objects.update(next_attempt_at=timezone.now())
                call_command("send_password_resets")
                if attempt < 2:
                    self.assertGreater(
                        PasswordResetRequest.objects.get().next_attempt_at,
                        timezone.now(),
                    )
                    call_command("send_password_resets")
                    self.assertEqual(sender.call_count, attempt + 1)
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_concurrent_consumption_has_exactly_one_winner(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")

        def consume():
            close_old_connections()
            try:
                confirm_recovery(
                    self.uid, self.token, "ConcurrentSyntheticPassword638!"
                )
                return True
            except Exception as exc:
                from rest_framework.exceptions import ValidationError

                if isinstance(exc, ValidationError):
                    return False
                raise
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(
                sorted(executor.map(lambda _: consume(), range(2))), [False, True]
            )
