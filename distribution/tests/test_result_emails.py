from datetime import timedelta
from io import StringIO
from smtplib import SMTPRecipientsRefused
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from distribution import dispatch
from distribution.models import ResultEmail
from distribution.services import schedule_result_email
from students.models import Enrollment, Student
from submissions.models import Submission


SEND = "distribution.dispatch.EmailMessage.send"


class ResultEmailTestMixin:
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
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
            max_mark=100,
            weight=20,
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="12345678@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def create_verified_submission(self, enrollment=None):
        return Submission.objects.create(
            assessment=self.assessment,
            enrollment=enrollment or self.enrollment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.VERIFIED,
        )

    def mark(self, submission, mark):
        return self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": mark},
            format="json",
        )

    def make_due(self, email):
        ResultEmail.objects.filter(pk=email.pk).update(
            run_after=timezone.now(),
        )


class MarkingSchedulesEmailTests(ResultEmailTestMixin, TestCase):
    def test_marking_saves_result_and_queues_email(self):
        response = self.mark(self.create_verified_submission(), 75)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["mark"], "75.00")

        email = ResultEmail.objects.get()

        self.assertEqual(email.status, ResultEmail.Status.QUEUED)
        self.assertEqual(email.recipient, "12345678@example.com")
        self.assertIn("75", email.body)
        self.assertEqual(email.result_version, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_worker_sends_queued_email(self):
        self.mark(self.create_verified_submission(), 75)

        self.assertTrue(dispatch.process_next_email())

        email = ResultEmail.objects.get()

        self.assertEqual(email.status, ResultEmail.Status.SENT)
        self.assertIsNotNone(email.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["12345678@example.com"])

    def test_mail_failure_after_save_keeps_mark(self):
        submission = self.create_verified_submission()

        self.mark(submission, 75)

        with patch(SEND, side_effect=ConnectionError("SMTP down")):
            dispatch.process_next_email()

        submission.refresh_from_db()
        email = ResultEmail.objects.get()

        self.assertEqual(submission.status, Submission.Status.MARKED)
        self.assertEqual(Result.objects.get().mark, 75)
        self.assertEqual(email.status, ResultEmail.Status.QUEUED)
        self.assertEqual(
            email.failure_reason,
            ResultEmail.FailureReason.PROVIDER_ERROR,
        )

    def test_invalid_mark_creates_no_email(self):
        response = self.mark(self.create_verified_submission(), 150)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ResultEmail.objects.exists())


class DuplicateRequestTests(ResultEmailTestMixin, TestCase):
    def test_repeated_mark_request_is_rejected_and_sends_once(self):
        submission = self.create_verified_submission()

        self.mark(submission, 75)
        second = self.mark(submission, 75)

        dispatch.process_next_email()
        dispatch.process_next_email()

        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ResultEmail.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_scheduling_same_version_twice_reuses_email(self):
        result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=60,
        )

        first = schedule_result_email(result)
        second = schedule_result_email(result)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.idempotency_key, f"result-{result.pk}-v1")

    def test_email_is_not_claimed_twice(self):
        self.mark(self.create_verified_submission(), 75)

        self.assertIsNotNone(dispatch.claim_next_email())
        self.assertIsNone(dispatch.claim_next_email())

    def test_retries_share_a_stable_message_id(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        dispatch.process_next_email()

        self.assertEqual(
            mail.outbox[0].extra_headers["Message-ID"],
            dispatch.message_id(email),
        )
        self.assertIn(email.idempotency_key, dispatch.message_id(email))


class RetryTests(ResultEmailTestMixin, TestCase):
    def test_provider_errors_retry_with_backoff(self):
        self.mark(self.create_verified_submission(), 75)

        with patch(SEND, side_effect=ConnectionError("SMTP down")):
            dispatch.process_next_email()

        email = ResultEmail.objects.get()

        self.assertEqual(email.attempts, 1)
        self.assertGreater(email.run_after, timezone.now())
        self.assertIsNone(dispatch.claim_next_email())

    def test_retries_are_bounded(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        with patch(SEND, side_effect=ConnectionError("SMTP down")):
            for _ in range(email.max_attempts):
                self.make_due(email)
                dispatch.process_next_email()

        email.refresh_from_db()

        self.assertEqual(email.status, ResultEmail.Status.FAILED)
        self.assertEqual(email.attempts, email.max_attempts)
        self.assertEqual(len(mail.outbox), 0)

    def test_retry_succeeds_after_transient_error(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        with patch(SEND, side_effect=ConnectionError("SMTP down")):
            dispatch.process_next_email()

        self.make_due(email)
        dispatch.process_next_email()

        email.refresh_from_db()

        self.assertEqual(email.status, ResultEmail.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_refused_recipient_is_not_retried(self):
        self.mark(self.create_verified_submission(), 75)

        refused = SMTPRecipientsRefused(
            {"12345678@example.com": (550, b"User unknown")}
        )

        with patch(SEND, side_effect=refused):
            dispatch.process_next_email()

        email = ResultEmail.objects.get()

        self.assertEqual(email.status, ResultEmail.Status.FAILED)
        self.assertEqual(
            email.failure_reason,
            ResultEmail.FailureReason.RECIPIENT_REFUSED,
        )


class MissingAddressTests(ResultEmailTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.student.email = ""
        self.student.save()

    def test_missing_address_keeps_mark_and_fails_email(self):
        response = self.mark(self.create_verified_submission(), 75)

        email = ResultEmail.objects.get()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Result.objects.get().mark, 75)
        self.assertEqual(email.status, ResultEmail.Status.FAILED)
        self.assertEqual(
            email.failure_reason,
            ResultEmail.FailureReason.MISSING_RECIPIENT,
        )
        self.assertFalse(dispatch.process_next_email())

    def test_retry_after_address_is_added(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        blocked = self.client.post(f"/api/result-emails/{email.id}/retry/")

        self.student.email = "fixed@example.com"
        self.student.save()

        retried = self.client.post(f"/api/result-emails/{email.id}/retry/")
        dispatch.process_next_email()

        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(retried.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(mail.outbox[0].to, ["fixed@example.com"])


class EditedMarkTests(ResultEmailTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.mark(self.create_verified_submission(), 60)
        self.result = Result.objects.get()

    def edit_mark(self, mark):
        return self.client.patch(
            f"/api/results/{self.result.id}/",
            {"mark": mark},
            format="json",
        )

    def test_mark_change_increments_version(self):
        self.edit_mark(70)
        self.result.refresh_from_db()

        self.assertEqual(self.result.version, 2)

    def test_unchanged_mark_keeps_version(self):
        self.edit_mark("60.00")
        self.result.refresh_from_db()

        self.assertEqual(self.result.version, 1)
        self.assertEqual(ResultEmail.objects.count(), 1)

    def test_edit_before_send_supersedes_old_email(self):
        self.edit_mark(70)

        dispatch.process_next_email()

        old = ResultEmail.objects.get(result_version=1)

        self.assertEqual(old.status, ResultEmail.Status.SUPERSEDED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("70", mail.outbox[0].body)

    def test_edit_after_send_sends_correction(self):
        dispatch.process_next_email()

        self.edit_mark(70)
        dispatch.process_next_email()

        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("60", mail.outbox[0].body)
        self.assertIn("70", mail.outbox[1].body)

    def test_mark_changed_while_email_claimed_is_not_sent(self):
        claimed = dispatch.claim_next_email()

        Result.objects.filter(pk=self.result.pk).update(version=2)
        dispatch.deliver_email(claimed, claimed.attempts)

        claimed.refresh_from_db()

        self.assertEqual(claimed.status, ResultEmail.Status.SUPERSEDED)
        self.assertEqual(len(mail.outbox), 0)

    def test_editing_unreleased_result_sends_nothing(self):
        other = Result.objects.create(
            assessment=Assessment.objects.create(
                course=self.course,
                name="Test 2",
                max_mark=100,
                weight=20,
            ),
            enrollment=self.enrollment,
            mark=50,
        )

        self.client.patch(
            f"/api/results/{other.id}/",
            {"mark": 55},
            format="json",
        )

        self.assertFalse(other.emails.exists())


class WorkerCrashTests(ResultEmailTestMixin, TestCase):
    def test_interrupted_send_becomes_delivery_unknown(self):
        self.mark(self.create_verified_submission(), 75)

        claimed = dispatch.claim_next_email()
        ResultEmail.objects.filter(pk=claimed.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.assertEqual(dispatch.recover_expired_sends(), 1)

        claimed.refresh_from_db()

        self.assertEqual(claimed.status, ResultEmail.Status.FAILED)
        self.assertEqual(
            claimed.failure_reason,
            ResultEmail.FailureReason.DELIVERY_UNKNOWN,
        )
        self.assertFalse(dispatch.process_next_email())

    def test_slow_send_that_completes_is_recorded_as_sent(self):
        self.mark(self.create_verified_submission(), 75)

        claimed = dispatch.claim_next_email()
        ResultEmail.objects.filter(pk=claimed.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        dispatch.recover_expired_sends()

        dispatch.mark_sent(claimed.pk, claimed.attempts)
        claimed.refresh_from_db()

        self.assertEqual(claimed.status, ResultEmail.Status.SENT)

    def test_delivery_unknown_retry_requires_confirmation(self):
        self.mark(self.create_verified_submission(), 75)

        claimed = dispatch.claim_next_email()
        ResultEmail.objects.filter(pk=claimed.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        dispatch.recover_expired_sends()

        url = f"/api/result-emails/{claimed.id}/retry/"

        unconfirmed = self.client.post(url)
        confirmed = self.client.post(
            url,
            {"confirm_duplicate": True},
            format="json",
        )

        self.assertEqual(unconfirmed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(confirmed.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(confirmed.data["status"], ResultEmail.Status.QUEUED)

    def test_worker_command_sends_queued_emails(self):
        self.mark(self.create_verified_submission(), 75)

        output = StringIO()

        # TestCase runs inside a transaction; the worker's connection
        # cleanup would close the test's own connection.
        with patch(
            "distribution.management.commands.run_mail_worker"
            ".close_old_connections"
        ):
            call_command("run_mail_worker", "--once", stdout=output)

        self.assertIn("Mail worker stopped.", output.getvalue())
        self.assertEqual(len(mail.outbox), 1)


class RecipientIsolationTests(ResultEmailTestMixin, TestCase):
    def test_each_student_receives_only_their_own_result(self):
        other_student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Bob",
            last_name="Jones",
            email="87654321@example.com",
        )
        other_enrollment = Enrollment.objects.create(
            course=self.course,
            student=other_student,
        )

        self.mark(self.create_verified_submission(), 75)
        self.mark(self.create_verified_submission(other_enrollment), 42)

        while dispatch.process_next_email():
            pass

        by_recipient = {
            message.to[0]: message for message in mail.outbox
        }

        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(all(len(m.to) == 1 for m in mail.outbox))
        self.assertTrue(all(not m.cc and not m.bcc for m in mail.outbox))
        self.assertIn("Alice", by_recipient["12345678@example.com"].body)
        self.assertIn("75", by_recipient["12345678@example.com"].body)
        self.assertIn("Bob", by_recipient["87654321@example.com"].body)
        self.assertIn("42", by_recipient["87654321@example.com"].body)


@override_settings(RESULT_EMAIL_RELEASE_POLICY="approval")
class ApprovalPolicyTests(ResultEmailTestMixin, TestCase):
    def test_email_awaits_approval_and_is_not_sent(self):
        self.mark(self.create_verified_submission(), 75)

        email = ResultEmail.objects.get()

        self.assertEqual(email.status, ResultEmail.Status.AWAITING_APPROVAL)
        self.assertFalse(dispatch.process_next_email())

    def test_preview_shows_recipient_and_result(self):
        self.mark(self.create_verified_submission(), 75)

        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/result-emails/"
        )

        preview = response.data[0]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(preview["recipient"], "12345678@example.com")
        self.assertEqual(preview["student_number"], "12345678")
        self.assertIn("75", preview["body"])
        self.assertTrue(preview["is_current"])
        self.assertNotIn("last_error", preview)

    def test_approved_email_is_sent(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        response = self.client.post(
            f"/api/result-emails/{email.id}/approve/"
        )
        dispatch.process_next_email()

        email.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(email.approved_by, self.user)
        self.assertEqual(email.status, ResultEmail.Status.SENT)

    def test_bulk_approve_releases_current_emails(self):
        self.mark(self.create_verified_submission(), 75)

        response = self.client.post(
            f"/api/assessments/{self.assessment.id}/result-emails/approve/"
        )

        self.assertEqual(response.data["approved"], 1)
        self.assertEqual(
            ResultEmail.objects.get().status,
            ResultEmail.Status.QUEUED,
        )

    def test_cannot_approve_outdated_email(self):
        self.mark(self.create_verified_submission(), 75)
        email = ResultEmail.objects.get()

        Result.objects.update(version=2)

        response = self.client.post(
            f"/api/result-emails/{email.id}/approve/"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OwnerIsolationTests(ResultEmailTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.mark(self.create_verified_submission(), 75)
        self.email = ResultEmail.objects.get()

        self.client.force_authenticate(user=self.other_user)

    def test_other_user_cannot_view_email(self):
        response = self.client.get(f"/api/result-emails/{self.email.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_user_cannot_list_assessment_emails(self):
        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/result-emails/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_user_cannot_approve_or_retry(self):
        approve = self.client.post(
            f"/api/result-emails/{self.email.id}/approve/"
        )
        retry = self.client.post(
            f"/api/result-emails/{self.email.id}/retry/"
        )
        bulk = self.client.post(
            f"/api/assessments/{self.assessment.id}/result-emails/approve/"
        )

        self.assertEqual(approve.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(retry.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(bulk.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_view(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(f"/api/result-emails/{self.email.id}/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
