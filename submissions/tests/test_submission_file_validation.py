"""
Covers acceptance criterion: test mismatched extensions, malformed
files, and the size/page-count/dimension limits enforced before the
(expensive) OCR recognition pipeline ever touches a file.

submissions/validation.py's happy paths are already exercised
indirectly via the upload tests in test_submissions.py (they now
have to build real PDF/image bytes to get past validation). This
file focuses on the rejection paths, which weren't covered yet.
"""

import io
from unittest.mock import MagicMock, patch

import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.validation import (
    SubmissionFileValidationError,
    validate_submission_file,
)


def make_valid_pdf_bytes(pages=1, width=200, height=200):
    document = pymupdf.open()
    try:
        for _ in range(pages):
            document.new_page(width=width, height=height)
        return document.tobytes()
    finally:
        document.close()


def make_valid_image_bytes(fmt="JPEG", size=(100, 100)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=fmt)
    return buffer.getvalue()


class SubmissionFileValidationUnitTests(TestCase):
    """
    Exercises submissions/validation.validate_submission_file()
    directly, without going through the API, so each rejection
    reason can be checked in isolation.
    """

    def _assert_rejected(self, uploaded_file, message_fragment=None):
        with self.assertRaises(
            SubmissionFileValidationError
        ) as ctx:
            validate_submission_file(uploaded_file)

        if message_fragment is not None:
            self.assertIn(
                message_fragment,
                " ".join(ctx.exception.messages),
            )

    # -- valid content: happy paths -----------------------------

    def test_accepts_valid_pdf(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(),
            content_type="application/pdf",
        )
        validate_submission_file(uploaded_file)  # must not raise

    def test_accepts_valid_jpeg(self):
        uploaded_file = SimpleUploadedFile(
            "paper.jpg",
            make_valid_image_bytes("JPEG"),
            content_type="image/jpeg",
        )
        validate_submission_file(uploaded_file)  # must not raise

    def test_accepts_valid_png(self):
        uploaded_file = SimpleUploadedFile(
            "paper.png",
            make_valid_image_bytes("PNG"),
            content_type="image/png",
        )
        validate_submission_file(uploaded_file)  # must not raise

    def test_leaves_stream_position_at_zero_after_success(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(),
            content_type="application/pdf",
        )
        validate_submission_file(uploaded_file)
        self.assertEqual(uploaded_file.tell(), 0)

    # -- unsupported extension -----------------------------------

    def test_rejects_unsupported_extension(self):
        uploaded_file = SimpleUploadedFile(
            "paper.docx",
            b"whatever",
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        )
        self._assert_rejected(uploaded_file, "Unsupported file type")

    def test_rejects_missing_extension(self):
        uploaded_file = SimpleUploadedFile(
            "paper",
            b"whatever",
            content_type="application/octet-stream",
        )
        self._assert_rejected(uploaded_file, "Unsupported file type")

    # -- mismatched extension vs actual content -------------------

    def test_rejects_png_content_with_jpg_extension(self):
        uploaded_file = SimpleUploadedFile(
            "paper.jpg",
            make_valid_image_bytes("PNG"),
            content_type="image/jpeg",
        )
        self._assert_rejected(
            uploaded_file,
            "does not match its actual",
        )

    def test_rejects_jpeg_content_with_png_extension(self):
        uploaded_file = SimpleUploadedFile(
            "paper.png",
            make_valid_image_bytes("JPEG"),
            content_type="image/png",
        )
        self._assert_rejected(
            uploaded_file,
            "does not match its actual",
        )

    def test_rejects_plain_text_renamed_to_pdf(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            b"This is just plain text, not a real PDF.",
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "not a valid PDF")

    def test_rejects_plain_text_renamed_to_jpg(self):
        uploaded_file = SimpleUploadedFile(
            "paper.jpg",
            b"This is just plain text, not a real image.",
            content_type="image/jpeg",
        )
        self._assert_rejected(uploaded_file, "not a valid image")

    # -- malformed / truncated files -------------------------------

    def test_rejects_truncated_pdf(self):
        valid_bytes = make_valid_pdf_bytes()
        truncated = valid_bytes[: len(valid_bytes) // 2]

        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            truncated,
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "not a valid PDF")

    def test_rejects_truncated_image(self):
        valid_bytes = make_valid_image_bytes("PNG")
        truncated = valid_bytes[: len(valid_bytes) // 2]

        uploaded_file = SimpleUploadedFile(
            "paper.png",
            truncated,
            content_type="image/png",
        )
        self._assert_rejected(uploaded_file, "not a valid image")

    def test_rejects_empty_file(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            b"",
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "not a valid PDF")

    # -- size / page-count / dimension limits ----------------------

    # NOTE: validation.py reads MAX_SUBMISSION_FILE_SIZE_BYTES /
    # MAX_SUBMISSION_PDF_PAGES / MAX_SUBMISSION_IMAGE_DIMENSION_PX
    # into module-level constants once, at import time (a normal
    # Django settings-caching pattern). Django's override_settings
    # patches django.conf.settings afterwards, which those already
    # module-level constants never see - so the limits below are
    # patched directly on the validation module instead.

    @patch("submissions.validation.MAX_FILE_SIZE_BYTES", 100)
    def test_rejects_file_over_size_limit(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(),
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "too large")

    @patch("submissions.validation.MAX_PDF_PAGES", 1)
    def test_rejects_pdf_with_too_many_pages(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(pages=2),
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "too many pages")

    def test_rejects_pdf_with_no_pages(self):
        # PyMuPDF refuses to save a genuinely zero-page PDF, so a
        # zero-page document is simulated directly rather than
        # built from real bytes.
        empty_document = MagicMock()
        empty_document.page_count = 0

        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(),
            content_type="application/pdf",
        )

        with patch(
            "submissions.validation.pymupdf.open",
            return_value=empty_document,
        ):
            self._assert_rejected(uploaded_file, "no pages")

    @patch("submissions.validation.MAX_IMAGE_DIMENSION_PX", 50)
    def test_rejects_image_over_dimension_limit(self):
        uploaded_file = SimpleUploadedFile(
            "paper.jpg",
            make_valid_image_bytes("JPEG", size=(200, 200)),
            content_type="image/jpeg",
        )
        self._assert_rejected(uploaded_file, "dimensions exceed")

    @patch("submissions.validation.MAX_IMAGE_DIMENSION_PX", 50)
    def test_rejects_pdf_page_over_dimension_limit_when_rendered(
        self,
    ):
        # A single, small-looking PDF page can still rasterize to
        # something huge at the 2x scale recognition renders at, so
        # the *decoded* dimensions must be checked, not just the
        # PDF's declared page size.
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            make_valid_pdf_bytes(width=2000, height=2000),
            content_type="application/pdf",
        )
        self._assert_rejected(uploaded_file, "exceeds the allowed")


class SubmissionFileValidationAPITests(TestCase):
    """
    Confirms rejected uploads never reach the database or storage,
    and that the error response never echoes back file content.
    """

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
            max_mark=100,
            weight=20,
        )

        self.client.force_authenticate(user=self.user)

    def test_upload_rejects_mismatched_extension(self):
        from submissions.models import Submission

        uploaded_file = SimpleUploadedFile(
            "student-paper.jpg",
            make_valid_pdf_bytes(),
            content_type="image/jpeg",
        )

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertFalse(Submission.objects.exists())

    def test_upload_rejects_malformed_file(self):
        from submissions.models import Submission

        uploaded_file = SimpleUploadedFile(
            "student-paper.pdf",
            b"not actually a pdf",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertFalse(Submission.objects.exists())

    def test_rejected_upload_response_does_not_echo_file_bytes(self):
        secret_looking_bytes = (
            b"CONFIDENTIAL STUDENT ANSWER: not a real pdf"
        )
        uploaded_file = SimpleUploadedFile(
            "student-paper.pdf",
            secret_looking_bytes,
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn(
            secret_looking_bytes,
            response.content,
        )