from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import RecognitionAttempt, Submission
from submissions.recognition.service import (
    recognize_submission,
)
from submissions.recognition.types import (
    ImageQualityResult,
    StudentNumberCandidate,
    StudentNumberRegion,
)
from submissions.tests.helpers import TemporaryMediaMixin


def region_for(text):
    return StudentNumberRegion(
        text=text,
        confidence=0.95,
        box=(0, 0, 10, 10),
        image_width=100,
        image_height=100,
    )


class SubmissionRecognitionServiceTests(TemporaryMediaMixin, TestCase):
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
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_recognizes_enrollment_from_submission(
        self,
        mock_assess_quality,
        mock_locate,
        mock_extract_candidate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

        mock_locate.return_value = region_for(
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
            enrollment.enrollment,
            self.enrollment,
        )
        self.assertIsNone(enrollment.reason)

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_returns_none_when_student_number_is_not_recognized(
        self,
        mock_assess_quality,
        mock_locate,
        mock_extract_candidate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

        mock_locate.return_value = region_for(
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

        self.assertIsNone(enrollment.enrollment)
        self.assertEqual(
            enrollment.reason,
            "Student number could not be matched",
        )

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_does_not_match_student_from_another_course(
        self,
        mock_assess_quality,
        mock_locate,
        mock_extract_candidate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

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

        mock_locate.return_value = region_for(
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

        self.assertIsNone(enrollment.enrollment)
        self.assertEqual(
            enrollment.reason,
            "Student number could not be matched",
        )

    @patch(
        "submissions.recognition.service."
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_returns_none_when_student_number_line_is_not_found(
        self,
        mock_assess_quality,
        mock_locate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

        mock_locate.return_value = None

        enrollment = recognize_submission(
            self.submission,
        )

        self.assertIsNone(enrollment.enrollment)
        self.assertEqual(
            enrollment.reason,
            "Student number area could not be identified",
        )

    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_stops_recognition_when_image_quality_is_poor(
        self,
        mock_assess_quality,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=False,
            reason="Image is too blurry",
        )

        result = recognize_submission(
            self.submission
        )

        attempt = RecognitionAttempt.objects.get(
            submission=self.submission,
        )

        self.assertIsNone(result.enrollment)
        self.assertEqual(result.reason, "Image is too blurry")
        self.assertEqual(
            attempt.outcome,
            RecognitionAttempt.Outcome.IMAGE_UNUSABLE,
        )
        self.assertEqual(attempt.quality_issues, ["Image is too blurry"])

    @patch(
        "submissions.recognition.service."
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_error_attempt_records_error_details(
        self,
        mock_assess_quality,
        mock_locate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

        mock_locate.side_effect = RuntimeError("OCR failed")

        with self.assertRaises(RuntimeError):
            recognize_submission(self.submission)

        attempt = RecognitionAttempt.objects.get(
            submission=self.submission,
        )

        self.assertEqual(
            attempt.outcome,
            RecognitionAttempt.Outcome.ERROR,
        )
        self.assertEqual(attempt.error_type, "RuntimeError")
        self.assertEqual(attempt.error_message, "OCR failed")

    @patch(
        "submissions.recognition.service."
        "extract_student_number_candidate"
    )
    @patch(
        "submissions.recognition.service."
        "locate_student_number"
    )
    @patch(
        "submissions.recognition.service."
        "assess_image_quality"
    )
    def test_attempt_records_every_candidate(
        self,
        mock_assess_quality,
        mock_locate,
        mock_extract_candidate,
    ):
        mock_assess_quality.return_value = ImageQualityResult(
            usable=True,
            reason=None
        )

        mock_locate.return_value = region_for(
            "Student number / Studentenommer: 37279432"
        )

        mock_extract_candidate.return_value = [
            StudentNumberCandidate(value="37279432", confidence=0.95),
            StudentNumberCandidate(value="37279433", confidence=0.40),
        ]

        recognize_submission(self.submission)

        attempt = RecognitionAttempt.objects.get(
            submission=self.submission,
        )

        self.assertEqual(attempt.raw_candidate, "37279432")
        self.assertEqual(
            attempt.raw_candidates,
            [
                {"value": "37279432", "confidence": 0.95},
                {"value": "37279433", "confidence": 0.40},
            ],
        )
