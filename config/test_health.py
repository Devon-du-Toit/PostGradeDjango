from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, override_settings

LIVE = "/health/live/"
READY = "/health/ready/"


class HealthCheckTests(TestCase):
    def test_live_answers_without_touching_the_database(self):
        with self.assertNumQueries(0):
            response = self.client.get(LIVE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_ready_checks_the_database_once(self):
        with self.assertNumQueries(1):
            response = self.client.get(READY)

        self.assertEqual(response.status_code, 200)

    def test_ready_returns_503_when_the_database_is_unreachable(self):
        with patch(
            "config.health.connection.cursor",
            side_effect=OperationalError("connection refused"),
        ):
            response = self.client.get(READY)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_probes_need_no_login(self):
        for path in (LIVE, READY):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    @override_settings(ALLOWED_HOSTS=["api.example.com"])
    def test_probe_from_an_internal_ip_is_not_rejected(self):
        response = self.client.get(LIVE, HTTP_HOST="10.0.0.5")

        self.assertEqual(response.status_code, 200)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_probe_is_not_redirected_to_https(self):
        response = self.client.get(READY)

        self.assertEqual(response.status_code, 200)

    def test_only_get_is_allowed(self):
        self.assertEqual(self.client.post(LIVE).status_code, 405)

    @override_settings(ALLOWED_HOSTS=["api.example.com"])
    def test_other_paths_still_validate_the_host(self):
        response = self.client.get("/api/courses/", HTTP_HOST="10.0.0.5")

        self.assertEqual(response.status_code, 400)
