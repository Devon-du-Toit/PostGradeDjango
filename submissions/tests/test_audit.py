
from django.test import TestCase

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.models import Submission, SubmissionAudit


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
