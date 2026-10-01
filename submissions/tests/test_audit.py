
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission


class SubmissionAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )
        self.course = Course.objects.create(
            owner=self.user,
            code="CS101",
            name="Intro to CS",
            year=2026,
            semester=1,
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=100,
            weight=50,
        )

    def _make_submission(self, filename="test.pdf"):
        return Submission.objects.create(
            assessment=self.assessment,
            original_filename=filename,
            status=Submission.Status.UPLOADED,
        )

    def test_audit_row_records_status_change(self):
        submission = self._make_submission()

        audit = submission.record_status_change(
            actor=self.user,
            new_status=Submission.Status.MATCHED,
            reason="test audit",
        )

        self.assertIsNotNone(audit.pk)
        self.assertEqual(audit.submission, submission)
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.previous_status, Submission.Status.UPLOADED)
        self.assertEqual(audit.new_status, Submission.Status.MATCHED)
        self.assertEqual(audit.reason, "test audit")

    def test_audit_entries_related_name(self):
        submission = self._make_submission("test2.pdf")

        submission.record_status_change(
            actor=self.user,
            new_status=Submission.Status.MATCHED,
            reason="first change",
        )
        submission.record_status_change(
            actor=self.user,
            new_status=Submission.Status.VERIFIED,
            reason="second change",
        )

        self.assertEqual(submission.audit_entries.count(), 2)

    def test_audit_without_actor(self):
        submission = self._make_submission("test3.pdf")

        audit = submission.record_status_change(
            actor=None,
            new_status=Submission.Status.MATCHED,
            reason="system change",
        )

        self.assertIsNone(audit.actor)

    def test_illegal_transition_raises(self):
        submission = self._make_submission("test4.pdf")

        with self.assertRaises(ValueError):
            submission.record_status_change(
                actor=self.user,
                new_status=Submission.Status.VERIFIED,
                reason="illegal jump",
            )

    def _enrollment(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )
        return Enrollment.objects.create(course=self.course, student=student)

    def test_failed_recognition_can_be_verified_by_hand(self):
        submission = self._make_submission("failed.pdf")
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.RECOGNITION_FAILED,
        )
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)

        response = api_client.post(
            f"/api/submissions/{submission.id}/verify/",
            {"enrollment": self._enrollment().id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.VERIFIED)
        self.assertEqual(
            submission.audit_entries.get().previous_status,
            Submission.Status.RECOGNITION_FAILED,
        )

    def test_illegal_verify_returns_400_not_500(self):
        submission = self._make_submission("uploaded.pdf")
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)

        response = api_client.post(
            f"/api/submissions/{submission.id}/verify/",
            {"enrollment": self._enrollment().id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Illegal transition", response.data["detail"])
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.UPLOADED)

    def test_stale_update_is_rejected(self):
        submission = self._make_submission("test_stale.pdf")
        original_version = submission.version

        # Simulate another client updating the row first.
        submission.record_status_change(
            actor=self.user,
            new_status=Submission.Status.MATCHED,
            reason="first write",
        )
        submission.refresh_from_db()

        # Now a second client sends an update using the version it read
        # before the first write happened.
        from rest_framework.test import APIClient

        api_client = APIClient()
        api_client.force_authenticate(user=self.user)
        response = api_client.patch(
            f"/api/submissions/{submission.id}/",
            {
                "version": original_version,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("version", response.data)

        submission.refresh_from_db()
        self.assertEqual(
            submission.status,
            Submission.Status.MATCHED,
        )
