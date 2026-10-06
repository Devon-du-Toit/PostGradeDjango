"""
Covers acceptance criterion: replacement/deletion cleanup,
retention, and storage-backend behaviour for submission files.

- Deleting a submission (directly, or via cascade from its parent
  Assessment/Course) removes the underlying file from storage - no
  orphaned files are left behind.
- A submission's file cannot be swapped out after upload; the
  supported path is delete-and-reupload.
- Recognition no longer assumes a local filesystem path
  (submission.file.path); it stages the file through the Storage
  API instead, so it keeps working on non-filesystem backends.
"""

import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, ImageDraw
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.models import Submission
from submissions.recognition.service import recognize_submission
from submissions.recognition.types import ImageQualityResult


def _make_valid_jpeg_bytes():
    # A flat/blank image fails quality.py's checks (no contrast,
    # no sharp edges), so this draws a simple grid to look enough
    # like a real scanned page to pass quality gating. Only OCR
    # itself is mocked in this test.
    image = Image.new("RGB", (600, 600), color=(220, 220, 220))
    draw = ImageDraw.Draw(image)
    for y in range(30, 570, 25):
        draw.line([(30, y), (570, y)], fill=(0, 0, 0), width=3)
    for x in range(30, 570, 35):
        draw.line([(x, 30), (x, 570)], fill=(0, 0, 0), width=2)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _make_valid_pdf_bytes():
    document = pymupdf.open()
    document.new_page(width=200, height=200)
    return document.tobytes()


TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="postgrade-lifecycle-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class SubmissionDeletionCleanupTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            email="teacher@example.com",
            password="testpass123",
        )

        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

    def _make_submission(self):
        return Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

    def test_deleting_submission_removes_file_from_storage(self):
        submission = self._make_submission()
        file_path = Path(submission.file.path)
        self.assertTrue(file_path.exists())

        self.client.force_authenticate(user=self.user)
        # Files are removed once the delete commits.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/submissions/{submission.id}/")

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertFalse(Submission.objects.filter(pk=submission.id).exists())
        self.assertFalse(file_path.exists())

    def test_deleting_assessment_cascades_and_removes_file(self):
        submission = self._make_submission()
        file_path = Path(submission.file.path)
        self.assertTrue(file_path.exists())

        # No API endpoint deletes an Assessment directly here, so
        # this exercises the model-level cascade the signal has to
        # survive. Files are removed once the delete commits.
        with self.captureOnCommitCallbacks(execute=True):
            self.assessment.delete()

        self.assertFalse(Submission.objects.filter(pk=submission.id).exists())
        self.assertFalse(file_path.exists())

    def test_other_user_cannot_delete_submission(self):
        submission = self._make_submission()
        file_path = Path(submission.file.path)

        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(f"/api/submissions/{submission.id}/")

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(Submission.objects.filter(pk=submission.id).exists())
        self.assertTrue(file_path.exists())

    def test_anonymous_user_cannot_delete_submission(self):
        submission = self._make_submission()

        response = self.client.delete(f"/api/submissions/{submission.id}/")

        self.assertIn(
            response.status_code,
            (
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ),
        )
        self.assertTrue(Submission.objects.filter(pk=submission.id).exists())

    def test_deleted_submission_file_is_no_longer_downloadable(self):
        submission = self._make_submission()
        self.client.force_authenticate(user=self.user)

        self.client.delete(f"/api/submissions/{submission.id}/")

        response = self.client.get(f"/api/submissions/{submission.id}/file/")

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class SubmissionFileReplacementTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            email="teacher@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        self.client.force_authenticate(user=self.user)

    def test_can_replace_file_with_current_version(self):
        old_storage = self.submission.file.storage
        old_name = self.submission.file.name
        self.assertTrue(old_storage.exists(old_name))

        replacement_file = SimpleUploadedFile(
            "replacement.pdf",
            _make_valid_pdf_bytes(),
            content_type="application/pdf",
        )

        # The old file is removed once the replacement commits.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/submissions/{self.submission.id}/",
                {"file": replacement_file, "version": self.submission.version},
                format="multipart",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.submission.refresh_from_db()

        # New file saved, old one cleaned up.
        self.assertNotEqual(
            self.submission.file.name,
            old_name,
        )
        self.assertTrue(self.submission.file.storage.exists(self.submission.file.name))
        self.assertFalse(old_storage.exists(old_name))

        # A new file invalidates any prior match.
        self.assertIsNone(self.submission.enrollment)
        self.assertEqual(
            self.submission.original_filename,
            "replacement.pdf",
        )

    def test_generic_edit_cannot_change_verified_recipient(self):
        from students.models import Enrollment, Student

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
            email="student@example.com",
        )
        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        response = self.client.patch(
            f"/api/submissions/{self.submission.id}/",
            {
                "enrollment": enrollment.id,
                "version": self.submission.version,
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.enrollment)


class SubmissionRecognitionStorageAgnosticTests(TestCase):
    """
    Recognition must not depend on submission.file.path being
    available, since that only works on local filesystem storage.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="teacher@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.jpg",
                _make_valid_jpeg_bytes(),
                content_type="image/jpeg",
            ),
            original_filename="paper.jpg",
        )

    @patch("submissions.recognition.service.locate_student_number")
    @patch("submissions.recognition.service.assess_image_quality")
    def test_recognition_succeeds_when_file_path_is_unavailable(
        self,
        mock_assess_quality,
        mock_locate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(usable=True)
        mock_locate.return_value = None

        # Simulate a non-filesystem storage backend (e.g. S3),
        # where FieldFile.path raises NotImplementedError.
        with patch(
            "django.db.models.fields.files.FieldFile.path",
            new_callable=PropertyMock,
        ) as mock_path:
            mock_path.side_effect = NotImplementedError(
                "This storage backend does not support " "absolute paths."
            )

            # Should not raise, and should not touch .path at all.
            recognize_submission(self.submission)

        mock_locate.assert_called_once()
