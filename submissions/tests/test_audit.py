
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
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

    def test_stale_instance_cannot_reverify_marked_submission(self):
        submission = self._make_submission()
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.MATCHED,
        )
        submission.refresh_from_db()
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.MARKED,
            version=4,
        )

        with self.assertRaisesMessage(ValueError, "from marked to verified"):
            submission.record_status_change(
                actor=self.user,
                new_status=Submission.Status.VERIFIED,
                new_enrollment=self._enrollment(),
            )

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.MARKED)
        self.assertEqual(submission.version, 4)
        self.assertIsNone(submission.enrollment)
        self.assertFalse(submission.audit_entries.exists())

    def test_transition_uses_current_status_and_enrollment(self):
        submission = self._make_submission()
        enrollment = self._enrollment()
        # The caller still sees uploaded/no enrollment; the row has moved on.
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.MATCHED,
            enrollment=enrollment,
            version=4,
        )

        audit = submission.record_status_change(
            actor=self.user,
            new_status=Submission.Status.VERIFIED,
        )

        self.assertEqual(audit.previous_status, Submission.Status.MATCHED)
        self.assertEqual(audit.previous_enrollment, enrollment)
        self.assertEqual(audit.new_enrollment, enrollment)
        self.assertEqual(submission.status, Submission.Status.VERIFIED)
        self.assertEqual(submission.enrollment, enrollment)
        self.assertEqual(submission.version, 5)
        self.assertEqual(
            submission.updated_at,
            Submission.objects.get(pk=submission.pk).updated_at,
        )

    def test_transition_saves_locked_instance_instead_of_caller(self):
        submission = self._make_submission()
        saved_instances = []
        original_save = Submission.save

        def record_save(instance, *args, **kwargs):
            saved_instances.append(instance)
            return original_save(instance, *args, **kwargs)

        with patch.object(Submission, "save", record_save):
            submission.record_status_change(
                actor=self.user,
                new_status=Submission.Status.MATCHED,
            )

        self.assertEqual(len(saved_instances), 1)
        self.assertIsNot(saved_instances[0], submission)
        self.assertEqual(saved_instances[0].pk, submission.pk)

    def test_audit_failure_rolls_back_status_and_version(self):
        submission = self._make_submission()
        with patch.object(
            SubmissionAudit.objects, "create", side_effect=RuntimeError("audit failed")
        ):
            with self.assertRaisesMessage(RuntimeError, "audit failed"):
                submission.record_status_change(
                    actor=self.user,
                    new_status=Submission.Status.MATCHED,
                )

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.UPLOADED)
        self.assertEqual(submission.version, 0)
        self.assertFalse(submission.audit_entries.exists())

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


class ConcurrentSubmissionTransitionTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_waiting_transition_revalidates_after_mark_commit(self):
        user = User.objects.create_user(
            email="locking@example.com", password="testpass123"
        )
        course = Course.objects.create(
            owner=user, code="LOCK101", name="Locking", year=2026, semester=1
        )
        assessment = Assessment.objects.create(
            course=course, name="Lock test", max_mark=100, weight=50
        )
        submission = Submission.objects.create(
            assessment=assessment,
            original_filename="locking.pdf",
            status=Submission.Status.VERIFIED,
        )
        stale = Submission.objects.get(pk=submission.pk)
        lock_attempted = Event()

        def competing_verification():
            close_old_connections()

            def observe_lock(execute, sql, params, many, context):
                if "FOR UPDATE" in sql.upper():
                    lock_attempted.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe_lock):
                    stale.record_status_change(
                        actor=None, new_status=Submission.Status.VERIFIED
                    )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked = Submission.objects.select_for_update().get(pk=submission.pk)
                locked.record_status_change(
                    actor=user, new_status=Submission.Status.MARKED
                )
                future = executor.submit(competing_verification)
                self.assertTrue(lock_attempted.wait(timeout=10))
                self.assertFalse(future.done())

            with self.assertRaisesMessage(ValueError, "from marked to verified"):
                future.result(timeout=10)

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.MARKED)
        self.assertEqual(submission.version, 1)
        self.assertEqual(submission.audit_entries.count(), 1)
        audit = submission.audit_entries.get()
        self.assertEqual(audit.previous_status, Submission.Status.VERIFIED)
        self.assertEqual(audit.new_status, Submission.Status.MARKED)
