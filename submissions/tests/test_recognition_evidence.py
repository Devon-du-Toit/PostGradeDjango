import os
from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.models import RecognitionAttempt, Submission
from submissions.tests.helpers import (
    PNG_SIGNATURE,
    TemporaryMediaMixin,
    make_png,
)


class RecognitionEvidenceTestMixin(TemporaryMediaMixin):
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


        )

        self.submission = Submission.objects.create(
            assessment=assessment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.NEEDS_VERIFICATION,
        )

        self.png = make_png()

        self.attempt = RecognitionAttempt(
            submission=self.submission,
            method=RecognitionAttempt.Method.OCR,
            outcome=RecognitionAttempt.Outcome.NO_MATCH,
            processing_version="ocr-1",
            raw_candidate="12345678",
            raw_candidates=[
                {"value": "12345678", "confidence": 0.9},
                {"value": "12345679", "confidence": 0.4},
            ],
        )
        self.attempt.region_image.save(
            "region.png",
            ContentFile(self.png),
            save=False,
        )
        self.attempt.save()

        self.client = APIClient()


class RecognitionEvidenceOwnerIsolationTests(
    RecognitionEvidenceTestMixin,
    TestCase,
):
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
        self.assertEqual(response.data["count"], 0)

    def test_other_user_verification_queue_excludes_evidence(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(
            "/api/submissions/verification-queue/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_owner_can_fetch_region_image(self):
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/recognition-image/"
        )

        content = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(content.startswith(PNG_SIGNATURE))
        self.assertEqual(content, self.png)

        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (40, 10))

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


class RecognitionEvidenceFieldTests(
    RecognitionEvidenceTestMixin,
    TestCase,
):
    def setUp(self):
        super().setUp()

        self.client.force_authenticate(user=self.owner)

    def test_all_candidates_are_exposed(self):
        response = self.client.get(
            f"/api/submissions/{self.submission.id}/"
        )

        self.assertEqual(
            response.data["recognition"]["raw_candidates"],
            [
                {"value": "12345678", "confidence": 0.9},
                {"value": "12345679", "confidence": 0.4},
            ],
        )

    def test_error_type_is_exposed_but_message_is_not(self):
        # Make the setUp attempt clearly older. Two inserts in a row can get
        # the same created_at on a coarse clock (Windows: ~0.4 ms), and then
        # "latest attempt" has no defined order.
        RecognitionAttempt.objects.filter(pk=self.attempt.pk).update(
            created_at=timezone.now() - timedelta(minutes=1),
        )

        RecognitionAttempt.objects.create(
            submission=self.submission,
            method=RecognitionAttempt.Method.OCR,
            outcome=RecognitionAttempt.Outcome.ERROR,
            processing_version="ocr-1",
            error_type="FileNotFoundError",
            error_message="C:\\secret\\media\\submissions\\test.pdf",
        )

        response = self.client.get(
            f"/api/submissions/{self.submission.id}/"
        )

        recognition = response.data["recognition"]

        self.assertEqual(recognition["outcome"], "error")
        self.assertEqual(recognition["error_type"], "FileNotFoundError")
        self.assertNotIn("error_message", recognition)
        self.assertNotIn("secret", str(response.data))


class RegionImageCleanupTests(
    RecognitionEvidenceTestMixin,
    TestCase,
):
    def test_deleting_submission_removes_region_image(self):
        path = self.attempt.region_image.path

        self.assertTrue(os.path.exists(path))

        with self.captureOnCommitCallbacks(execute=True):
            self.submission.delete()

        self.assertFalse(os.path.exists(path))

    def test_deleting_attempt_removes_region_image(self):
        path = self.attempt.region_image.path

        with self.captureOnCommitCallbacks(execute=True):
            self.attempt.delete()

        self.assertFalse(os.path.exists(path))

    def test_rolled_back_delete_keeps_region_image(self):
        path = self.attempt.region_image.path

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    self.submission.delete()
                    raise RuntimeError("roll back")
            except RuntimeError:
                pass

        self.assertEqual(callbacks, [])
        self.assertTrue(os.path.exists(path))
        self.assertTrue(
            RecognitionAttempt.objects.filter(pk=self.attempt.pk).exists()
        )

    def test_attempt_without_image_deletes_cleanly(self):
        self.attempt.region_image = ""
        self.attempt.save()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.attempt.delete()

        self.assertEqual(callbacks, [])
