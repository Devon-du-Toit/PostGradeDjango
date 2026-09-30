import pymupdf
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import RecognitionAttempt, Submission
from submissions.recognition.service import (
    recognize_submission,
)
from submissions.tests.helpers import PNG_SIGNATURE, TemporaryMediaMixin


class RecognitionIntegrationTests(TemporaryMediaMixin, TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="CMPG211",
            name="CMPG211",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Class Test 1",
            max_mark=20,
            weight=10,
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="37279432",
            first_name="Test",
            last_name="Student",
            email="student@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

    def test_recognizes_real_full_page_submission_with_ocr_error(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "student_numbers"
            / "full"
            / "student_35226455.jpeg"
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="35226455",
            first_name="Real",
            last_name="Student",
            email="real@example.com",
        )

        expected_enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "student_35226455.jpeg",
                fixture_path.read_bytes(),
                content_type="image/jpeg",
            ),
            original_filename="student_35226455.jpeg",
        )

        result = recognize_submission(
            submission,
        )

        self.assertEqual(
            result.enrollment,
            expected_enrollment,
        )

        # The stored crop of the student-number region is a real PNG.
        attempt = RecognitionAttempt.objects.get(submission=submission)

        with attempt.region_image.open("rb") as stored:
            content = stored.read()

        self.assertTrue(content.startswith(PNG_SIGNATURE))

        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(
                image.size,
                (attempt.region["width"], attempt.region["height"]),
            )

    def test_recognizes_student_from_real_pdf_submission(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "student_numbers"
            / "full"
            / "student_37279432_a.jpeg"
        )

        pdf_path = (
            Path(__file__).parent
            / "fixtures"
            / "student_numbers"
            / "student_37279432_test.pdf"
        )

        document = pymupdf.open()
        page = document.new_page()

        page.insert_image(
            page.rect,
            filename=str(fixture_path),
        )

        document.save(
            pdf_path,
        )
        document.close()

        try:
            submission = Submission.objects.create(
                assessment=self.assessment,
                file=SimpleUploadedFile(
                    "student_37279432.pdf",
                    pdf_path.read_bytes(),
                    content_type="application/pdf",
                ),
                original_filename="student_37279432.pdf",
            )

            result = recognize_submission(
                submission,
            )

            self.assertEqual(
                result.enrollment,
                self.enrollment,
            )

        finally:
            if pdf_path.exists():
                pdf_path.unlink()