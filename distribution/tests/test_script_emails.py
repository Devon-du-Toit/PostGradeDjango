from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from smtplib import SMTPRecipientsRefused
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from distribution.dispatch import (
    claim_next_email,
    deliver_email,
    process_next_email,
    recover_expired_sends,
)
from distribution.models import ScriptEmail
from distribution.services import (
    approve_assessment_emails,
    approve_email,
    retry_email,
    schedule_script_email,
)
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.tests.helpers import TemporaryMediaMixin, make_pdf
from submissions.verification import verify_submission


class ScriptFixture(TemporaryMediaMixin):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            email="lecturer@example.invalid", password="synthetic"
        )
        self.course = Course.objects.create(
            owner=self.user, code="SYN101", name="Synthetic", year=2026, semester=1
        )
        self.assessment = Assessment.objects.create(course=self.course, name="Test")
        self.student = Student.objects.create(
            owner=self.user,
            student_number="00123456",
            first_name="Ava",
            last_name="Example",
            email="ava@example.invalid",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course, student=self.student
        )
        self.bytes = make_pdf()
        self.submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            status="verified",
            version=1,
            file=SimpleUploadedFile(
                "script.pdf", self.bytes, content_type="application/pdf"
            ),
            original_filename="script.pdf",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCRIPT_EMAIL_RELEASE_POLICY="automatic",
)
class ScriptEmailTests(ScriptFixture, TestCase):
    def schedule(self):
        return schedule_script_email(self.submission)

    def test_explicit_request_is_idempotent_and_does_not_change_verified_status(self):
        url = f"/api/submissions/{self.submission.pk}/email/"
        first = self.client.post(url)
        second = self.client.post(url)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(ScriptEmail.objects.count(), 1)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, "verified")
        self.assertEqual(first.data["attachment_filename"], "script.pdf")
        self.assertNotIn("result", first.data)

    def test_worker_sends_exact_script_attachment_to_only_verified_student(self):
        email = self.schedule()
        self.assertTrue(process_next_email())
        email.refresh_from_db()
        self.assertEqual(email.status, "sent")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ava@example.invalid"])
        self.assertEqual(message.subject, "PostGrade script: Test")
        self.assertNotIn("mark", message.body.lower())
        attachment = message.attachments[0]
        self.assertEqual(attachment.filename, "script.pdf")
        self.assertEqual(attachment.content, self.bytes)
        self.assertEqual(attachment.mimetype, "application/pdf")

    def test_unverified_script_cannot_be_scheduled(self):
        self.submission.status = "matched"
        self.submission.save()
        self.assertEqual(
            self.client.post(
                f"/api/submissions/{self.submission.pk}/email/"
            ).status_code,
            400,
        )
        self.assertFalse(ScriptEmail.objects.exists())

    def test_other_lecturer_and_anonymous_cannot_schedule_or_view_deliveries(self):
        email = self.schedule()
        other = User.objects.create_user(email="other@example.invalid")
        self.client.force_authenticate(other)
        for url in [
            f"/api/submissions/{self.submission.pk}/email/",
            f"/api/script-emails/{email.pk}/approve/",
            f"/api/script-emails/{email.pk}/retry/",
        ]:
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/script-emails/{email.pk}/").status_code, 404
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(
                f"/api/submissions/{self.submission.pk}/email/"
            ).status_code,
            401,
        )

    def test_missing_recipient_is_recorded_and_corrected_address_is_used_on_retry(self):
        self.student.email = ""
        self.student.save()
        email = self.schedule()
        self.assertEqual(email.failure_reason, "missing_recipient")
        self.student.email = "corrected@example.invalid"
        self.student.save()
        retried = retry_email(email.pk)
        self.assertEqual(retried.recipient, "corrected@example.invalid")
        self.assertEqual(retried.status, "queued")

    @override_settings(SCRIPT_EMAIL_RELEASE_POLICY="approval")
    def test_approval_is_required_and_missing_address_retry_does_not_bypass_it(self):
        email = self.schedule()
        self.assertEqual(email.status, "awaiting_approval")
        self.assertFalse(process_next_email())
        self.assertEqual(approve_assessment_emails(self.assessment, self.user), 1)
        self.assertTrue(process_next_email())
        self.submission.version += 1
        self.submission.save()
        self.student.email = ""
        self.student.save()
        failed = self.schedule()
        self.student.email = "restored@example.invalid"
        self.student.save()
        replacement = retry_email(failed.pk)
        self.assertEqual(replacement.status, "awaiting_approval")
        self.assertEqual(approve_email(replacement.pk, self.user).status, "queued")

    def test_sent_records_cannot_be_retried(self):
        email = self.schedule()
        process_next_email()
        with self.assertRaises(ValidationError):
            retry_email(email.pk)

    @patch(
        "distribution.dispatch.EmailMessage.send",
        side_effect=RuntimeError("synthetic provider error"),
    )
    def test_provider_failure_retries_are_bounded(self, send):
        email = self.schedule()
        for _ in range(email.max_attempts):
            ScriptEmail.objects.filter(pk=email.pk).update(run_after=timezone.now())
            self.assertTrue(process_next_email())
        email.refresh_from_db()
        self.assertEqual(email.status, "failed")
        self.assertEqual(email.attempts, email.max_attempts)
        self.assertFalse(process_next_email())

    @patch("distribution.dispatch.EmailMessage.send", return_value=0)
    def test_backend_non_acceptance_is_not_reported_as_sent(self, send):
        email = self.schedule()
        process_next_email()
        email.refresh_from_db()
        self.assertEqual(email.status, "queued")
        self.assertIsNone(email.sent_at)

    @patch(
        "distribution.dispatch.EmailMessage.send",
        side_effect=SMTPRecipientsRefused({"ava@example.invalid": (550, b"refused")}),
    )
    def test_refused_recipient_is_not_automatically_retried(self, send):
        email = self.schedule()
        process_next_email()
        email.refresh_from_db()
        self.assertEqual(email.status, "failed")
        self.assertEqual(email.failure_reason, "recipient_refused")

    def test_unknown_delivery_requires_real_boolean_confirmation(self):
        email = self.schedule()
        claim_next_email()
        ScriptEmail.objects.filter(pk=email.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(recover_expired_sends(), 1)
        url = f"/api/script-emails/{email.pk}/retry/"
        self.assertEqual(
            self.client.post(
                url, {"confirm_duplicate": "false"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                url, {"confirm_duplicate": True}, format="json"
            ).status_code,
            202,
        )

    def test_missing_snapshot_never_sends_body_only_message(self):
        email = self.schedule()
        email.attachment.delete(save=False)
        process_next_email()
        email.refresh_from_db()
        self.assertEqual(email.status, "failed")
        self.assertEqual(email.failure_reason, "attachment_unavailable")
        self.assertEqual(len(mail.outbox), 0)

    def test_repeat_verification_keeps_same_delivery_version(self):
        email = self.schedule()
        verify_submission(self.submission, self.enrollment, self.user)
        self.assertEqual(self.schedule().pk, email.pk)
        self.assertEqual(self.submission.version, 1)

    def test_changed_student_supersedes_previous_delivery_and_snapshot(self):
        email = self.schedule()
        other = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Other",
            last_name="Example",
            email="other@example.invalid",
        )
        enrollment = Enrollment.objects.create(course=self.course, student=other)
        verify_submission(
            self.submission,
            enrollment,
            self.user,
            correction=True,
            expected_version=self.submission.version,
            reason="Corrected the selected student after reviewing the script",
        )
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")
        with self.assertRaises(ValidationError):
            retry_email(email.pk)
        replacement = self.schedule()
        self.assertNotEqual(replacement.pk, email.pk)
        self.assertEqual(replacement.recipient, other.email)

    def test_replacement_invalidates_delivery_preserves_old_copy_and_requires_reverification(
        self,
    ):
        email = self.schedule()
        response = self.client.patch(
            f"/api/submissions/{self.submission.pk}/",
            {"file": SimpleUploadedFile("new.pdf", make_pdf()), "version": 1},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")
        with email.attachment.open("rb") as file:
            self.assertEqual(file.read(), self.bytes)
        self.assertEqual(
            self.client.post(
                f"/api/submissions/{self.submission.pk}/email/"
            ).status_code,
            400,
        )

    def test_generic_edit_cannot_change_student_or_assessment_under_a_verified_script(
        self,
    ):
        another = Assessment.objects.create(course=self.course, name="Other")
        for data in [
            {"version": 1, "enrollment": None},
            {"version": 1, "assessment": another.pk},
        ]:
            self.assertEqual(
                self.client.patch(
                    f"/api/submissions/{self.submission.pk}/", data, format="json"
                ).status_code,
                400,
            )

    def test_archive_stops_queued_and_already_claimed_delivery(self):
        email = self.schedule()
        claimed = claim_next_email()
        self.assessment.archive()
        deliver_email(claimed, claimed.attempts)
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.client.post(
                f"/api/submissions/{self.submission.pk}/email/"
            ).status_code,
            404,
        )

    def test_archive_retains_sent_history_and_original(self):
        email = self.schedule()
        process_next_email()
        self.course.archive()
        email.refresh_from_db()
        self.assertEqual(email.status, "sent")
        self.assertTrue(email.attachment.storage.exists(email.attachment.name))
        self.assertTrue(self.submission.file.storage.exists(self.submission.file.name))

    def test_archiving_submission_retains_email_history_without_delivery(self):
        email = self.schedule()
        response = self.client.delete(
            f"/api/submissions/{self.submission.pk}/",
            {
                "version": self.submission.version,
                "reason": "Retain as historical script",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(process_next_email())
        email.refresh_from_db()
        self.assertEqual(email.submission_id, self.submission.pk)
        self.assertEqual(email.status, "superseded")
        self.assertTrue(email.attachment.storage.exists(email.attachment.name))
        self.submission.refresh_from_db()
        self.assertIsNotNone(self.submission.archived_at)

    def test_removed_grading_routes_are_unavailable_and_assessment_has_no_scores(self):
        for url in [
            f"/api/submissions/{self.submission.pk}/mark/",
            f"/api/assessments/{self.assessment.pk}/results/",
            f"/api/assessments/{self.assessment.pk}/statistics/",
            f"/api/courses/{self.course.pk}/gradebook/",
            "/api/results/1/",
            "/api/result-emails/1/",
        ]:
            self.assertEqual(self.client.post(url, {"mark": 75}).status_code, 404)
        response = self.client.get(f"/api/assessments/{self.assessment.pk}/")
        self.assertNotIn("max_mark", response.data)
        self.assertNotIn("weight", response.data)


@override_settings(SCRIPT_EMAIL_RELEASE_POLICY="automatic")
class ConcurrentScriptEmailTests(ScriptFixture, TransactionTestCase):
    def test_concurrent_requests_create_one_delivery_and_attachment(self):
        def schedule():
            close_old_connections()
            try:
                return schedule_script_email(self.submission).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(lambda _: schedule(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ScriptEmail.objects.count(), 1)
