import pymupdf
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pathlib import Path

from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.recognition.service import (
    recognize_submission,
)
from submissions.recognition.types import (
    StudentNumberCandidate,
)


class SubmissionRecognitionServiceTests(TestCase):
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

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "test.jpg",
                b"fake image",
                content_type="image/jpeg",
            ),
            original_filename="test.jpg",
        )

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "find_student_number_text"
    )
    def test_recognizes_enrollment_from_submission(
        self,
        mock_find_text,
        mock_extract_candidate,
    ):
        mock_find_text.return_value = (
            "Student number / Studentenommer: 37279432"
        )

        mock_extract_candidate.return_value = [
            StudentNumberCandidate(
                value="37279432",
                confidence=0.95,
            )
        ]

        enrollment = recognize_submission(
            self.submission,
        )

        self.assertEqual(
            enrollment,
            self.enrollment,
        )

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "find_student_number_text"
    )
    def test_returns_none_when_student_number_is_not_recognized(
        self,
        mock_find_text,
        mock_extract_candidate,
    ):
        mock_find_text.return_value = (
            "Student number / Studentenommer: 99999999"
        )

        mock_extract_candidate.return_value = [
            StudentNumberCandidate(
                value="99999999",
                confidence=0.95,
            )
        ]

        enrollment = recognize_submission(
            self.submission,
        )

        self.assertIsNone(enrollment)

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "find_student_number_text"
    )
    def test_does_not_match_student_from_another_course(
        self,
        mock_find_text,
        mock_extract_candidate,
    ):
        other_course = Course.objects.create(
            owner=self.user,
            code="CMPG212",
            name="CMPG212",
            year=2026,
            semester=1,
        )

        other_student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Other",
            last_name="Student",
            email="other@example.com",
        )

        Enrollment.objects.create(
            course=other_course,
            student=other_student,
        )

        mock_find_text.return_value = (
            "Student number / Studentenommer: 12345678"
        )

        mock_extract_candidate.return_value = [
            StudentNumberCandidate(
                value="12345678",
                confidence=0.99,
            )
        ]

        enrollment = recognize_submission(
            self.submission,
        )

        self.assertIsNone(enrollment)

    @patch(
        "submissions.recognition.service."
        "find_student_number_text"
    )
    def test_returns_none_when_student_number_line_is_not_found(
        self,
        mock_find_text,
    ):
        mock_find_text.return_value = None

        enrollment = recognize_submission(
            self.submission,
        )

        self.assertIsNone(enrollment)

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

        enrollment = recognize_submission(
            submission,
        )

        self.assertEqual(
            enrollment,
            expected_enrollment,
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

            enrollment = recognize_submission(
                submission,
            )

            self.assertEqual(
                enrollment,
                self.enrollment,
            )

        finally:
            if pdf_path.exists():
                pdf_path.unlink()