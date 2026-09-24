import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.models import RecognitionAttempt, Submission


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RecognitionEvidenceOwnerIsolationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )

        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        course = Course.objects.create(
            owner=self.owner,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        assessment = Assessment.objects.create(
            course=course,
            name="Test 1",
            max_mark=100,
            weight=20,
        )

        self.submission = Submission.objects.create(
            assessment=assessment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.NEEDS_VERIFICATION,
        )

        attempt = RecognitionAttempt(
            submission=self.submission,
            method=RecognitionAttempt.Method.OCR,
            outcome=RecognitionAttempt.Outcome.NO_MATCH,
            processing_version="ocr-1",
            raw_candidate="12345678",
        )
        attempt.region_image.save(
            "region.png",
            ContentFile(b"fake png"),
            save=False,
        )
        attempt.save()

        self.client = APIClient()

    def test_owner_sees_recognition_evidence(self):
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["recognition"]["raw_candidate"],
            "12345678",
        )

    def test_other_user_cannot_view_submission_evidence(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_other_user_list_excludes_submission_evidence(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get("/api/submissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_other_user_verification_queue_excludes_evidence(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(
            "/api/submissions/verification-queue/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_owner_can_fetch_region_image(self):
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/recognition-image/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_other_user_cannot_fetch_region_image(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/recognition-image/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_cannot_fetch_region_image(self):
        response = self.client.get(
            f"/api/submissions/{self.submission.id}/recognition-image/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )