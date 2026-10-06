from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.verification import verify_submission

from rest_framework import status
from rest_framework.test import APIClient


class SubmissionVerificationStatusTests(TestCase):
    def test_submission_has_verification_statuses(self):
        self.assertEqual(
            Submission.Status.NEEDS_VERIFICATION,
            "needs_verification",
        )
        self.assertEqual(
            Submission.Status.VERIFIED,
            "verified",
        )


class VerifySubmissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            name="Physics",
            code="PHY101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
            email="12345678@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.NEEDS_VERIFICATION,
        )

    def test_verify_submission_assigns_enrollment(self):
        verify_submission(
            self.submission,
            self.enrollment,
        )

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.enrollment,
            self.enrollment,
        )

    def test_verify_submission_sets_status_to_verified(self):
        verify_submission(
            self.submission,
            self.enrollment,
        )

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.status,
            Submission.Status.VERIFIED,
        )

    def test_verify_submission_rejects_enrollment_from_other_course(self):
        other_course = Course.objects.create(
            owner=self.user,
            name="Chemistry",
            code="CHE101",
            year=2026,
            semester=1,
        )

        other_student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Other",
            last_name="Student",
        )

        other_enrollment = Enrollment.objects.create(
            course=other_course,
            student=other_student,
        )

        with self.assertRaises(ValidationError):
            verify_submission(
                self.submission,
                other_enrollment,
            )


class SubmissionVerificationAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user,
        )

        self.course = Course.objects.create(
            owner=self.user,
            name="Physics",
            code="PHY101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
            email="12345678@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.NEEDS_VERIFICATION,
        )

    def test_verify_submission_endpoint(self):
        response = self.client.post(
            f"/api/submissions/{self.submission.id}/verify/",
            {
                "enrollment": self.enrollment.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.enrollment,
            self.enrollment,
        )

        self.assertEqual(
            self.submission.status,
            Submission.Status.VERIFIED,
        )

    def test_verify_requires_enrollment(self):
        response = self.client.post(
            f"/api/submissions/{self.submission.id}/verify/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_other_user_cannot_verify_submission(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        self.client.force_authenticate(
            user=other_user,
        )

        response = self.client.post(
            f"/api/submissions/{self.submission.id}/verify/",
            {
                "enrollment": self.enrollment.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.submission.refresh_from_db()

        self.assertIsNone(
            self.submission.enrollment,
        )

        self.assertEqual(
            self.submission.status,
            Submission.Status.NEEDS_VERIFICATION,
        )

    def test_verification_queue_returns_unverified_submissions(self):
        matched_submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            file="submissions/matched.pdf",
            original_filename="matched.pdf",
            status=Submission.Status.MATCHED,
        )

        verified_submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            file="submissions/verified.pdf",
            original_filename="verified.pdf",
            status=Submission.Status.VERIFIED,
        )

        response = self.client.get("/api/submissions/verification-queue/")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            self.submission.id,
            returned_ids,
        )

        self.assertIn(
            matched_submission.id,
            returned_ids,
        )

        self.assertNotIn(
            verified_submission.id,
            returned_ids,
        )

    def test_verification_queue_excludes_other_users_submissions(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        other_course = Course.objects.create(
            owner=other_user,
            name="Chemistry",
            code="CHE101",
            year=2026,
            semester=1,
        )

        other_assessment = Assessment.objects.create(
            course=other_course,
            name="Test 1",
        )

        other_submission = Submission.objects.create(
            assessment=other_assessment,
            file="submissions/other.pdf",
            original_filename="other.pdf",
            status=Submission.Status.NEEDS_VERIFICATION,
        )

        response = self.client.get("/api/submissions/verification-queue/")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data["results"]}

        self.assertNotIn(
            other_submission.id,
            returned_ids,
        )


class ConcurrentSubmissionWorkflowTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="concurrent@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            name="Physics",
            code="PHY201",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Concurrent Test",
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="98765432",
            first_name="Concurrent",
            last_name="Student",
            email="98765432@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            file="submissions/concurrent-test.pdf",
            original_filename="concurrent-test.pdf",
            status=Submission.Status.VERIFIED,
        )

    def test_concurrent_verification_attempts_keep_valid_status(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections

        def verify():
            close_old_connections()

            submission = Submission.objects.get(
                pk=self.submission.pk,
            )
            enrollment = Enrollment.objects.get(
                pk=self.enrollment.pk,
            )

            verify_submission(
                submission,
                enrollment,
            )

            close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(verify),
                executor.submit(verify),
            ]

            for future in futures:
                future.result()

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.status,
            Submission.Status.VERIFIED,
        )
