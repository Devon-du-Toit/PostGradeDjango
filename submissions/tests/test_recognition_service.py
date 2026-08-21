from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

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

    def test_recognizes_enrollment_from_submission(self):
        provider = Mock()

        provider.recognize.return_value = [
            StudentNumberCandidate(
                value="37279432",
                confidence=0.95,
            )
        ]

        enrollment = recognize_submission(
            submission=self.submission,
            provider=provider,
        )

        self.assertEqual(
            enrollment,
            self.enrollment,
        )

    def test_returns_none_when_student_number_is_not_recognized(self):
        provider = Mock()

        provider.recognize.return_value = [
            StudentNumberCandidate(
                value="99999999",
                confidence=0.95,
            )
        ]

        enrollment = recognize_submission(
            submission=self.submission,
            provider=provider,
        )

        self.assertIsNone(enrollment)

    def test_does_not_match_student_from_another_course(self):
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

        provider = Mock()

        provider.recognize.return_value = [
            StudentNumberCandidate(
                value="12345678",
                confidence=0.99,
            )
        ]

        enrollment = recognize_submission(
            submission=self.submission,
            provider=provider,
        )

        self.assertIsNone(enrollment)