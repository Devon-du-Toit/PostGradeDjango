import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions import jobs
from submissions.models import RecognitionJob, Submission
from submissions.verification import verify_submission


RECOGNIZE = "submissions.jobs.recognize_submission"


class RecognitionJobTestMixin:
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

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=Student.objects.create(
                owner=self.user,
                student_number="12345678",
                first_name="Test",
                last_name="Student",
                email="12345678@example.com",
            ),
        )

    def create_processing_submission(self):
        submission = Submission.objects.create(
            assessment=self.assessment,
            file="submissions/test.pdf",
            original_filename="test.pdf",
            status=Submission.Status.PROCESSING,
        )
        jobs.enqueue_recognition(submission)

        return submission

    def expire_lease(self, job):
        RecognitionJob.objects.filter(pk=job.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

    def make_due(self, job):
        RecognitionJob.objects.filter(pk=job.pk).update(
            run_after=timezone.now(),
        )


class EnqueueTests(RecognitionJobTestMixin, TestCase):
    def test_enqueue_creates_queued_job(self):
        submission = self.create_processing_submission()

        job = submission.recognition_jobs.get()

        self.assertEqual(job.status, RecognitionJob.Status.QUEUED)
        self.assertEqual(job.attempts, 0)

    def test_duplicate_enqueue_returns_existing_active_job(self):
        submission = self.create_processing_submission()

        first = submission.recognition_jobs.get()
        second = jobs.enqueue_recognition(submission)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(submission.recognition_jobs.count(), 1)

    def test_running_job_is_not_claimed_twice(self):
        self.create_processing_submission()

        self.assertIsNotNone(jobs.claim_next_job())
        self.assertIsNone(jobs.claim_next_job())


class JobOutcomeTests(RecognitionJobTestMixin, TestCase):
    def test_success_matches_submission(self):
        submission = self.create_processing_submission()

        with patch(RECOGNIZE, return_value=self.enrollment):
            jobs.process_next_job()

        submission.refresh_from_db()
        job = submission.recognition_jobs.get()

        self.assertEqual(job.status, RecognitionJob.Status.SUCCEEDED)
        self.assertEqual(submission.status, Submission.Status.MATCHED)
        self.assertEqual(submission.enrollment, self.enrollment)

    def test_no_match_needs_verification(self):
        submission = self.create_processing_submission()

        with patch(RECOGNIZE, return_value=None):
            jobs.process_next_job()

        submission.refresh_from_db()

        self.assertEqual(
            submission.status,
            Submission.Status.NEEDS_VERIFICATION,
        )

    def test_empty_queue_returns_false(self):
        self.assertFalse(jobs.process_next_job())


class RetryAndFailureTests(RecognitionJobTestMixin, TestCase):
    def test_failure_is_retried_with_backoff(self):
        submission = self.create_processing_submission()

        with patch(RECOGNIZE, side_effect=RuntimeError("OCR failed")):
            jobs.process_next_job()

        submission.refresh_from_db()
        job = submission.recognition_jobs.get()

        self.assertEqual(job.status, RecognitionJob.Status.QUEUED)
        self.assertEqual(job.attempts, 1)
        self.assertIn("RuntimeError: OCR failed", job.last_error)
        self.assertGreater(job.run_after, timezone.now())
        self.assertEqual(submission.status, Submission.Status.PROCESSING)

    def test_backed_off_job_is_not_claimed_early(self):
        self.create_processing_submission()

        with patch(RECOGNIZE, side_effect=RuntimeError("OCR failed")):
            jobs.process_next_job()

        self.assertIsNone(jobs.claim_next_job())

    def test_retries_are_bounded(self):
        submission = self.create_processing_submission()
        job = submission.recognition_jobs.get()

        with patch(RECOGNIZE, side_effect=RuntimeError("OCR failed")):
            for _ in range(job.max_attempts):
                self.make_due(job)
                jobs.process_next_job()

        submission.refresh_from_db()
        job.refresh_from_db()

        self.assertEqual(job.status, RecognitionJob.Status.FAILED)
        self.assertEqual(job.attempts, job.max_attempts)
        self.assertEqual(
            submission.status,
            Submission.Status.RECOGNITION_FAILED,
        )


class StaleResultTests(RecognitionJobTestMixin, TestCase):
    def test_late_result_does_not_overwrite_human_verification(self):
        submission = self.create_processing_submission()

        def verify_while_running(running_submission):
            verify_submission(
                Submission.objects.get(pk=running_submission.pk),
                self.enrollment,
            )
            return None

        with patch(RECOGNIZE, side_effect=verify_while_running):
            jobs.process_next_job()

        submission.refresh_from_db()

        self.assertEqual(submission.status, Submission.Status.VERIFIED)
        self.assertEqual(submission.enrollment, self.enrollment)

    def test_reclaimed_job_rejects_previous_workers_result(self):
        submission = self.create_processing_submission()

        claimed = jobs.claim_next_job()

        # Another worker reclaims the job after the lease expired.
        RecognitionJob.objects.filter(pk=claimed.pk).update(
            attempts=claimed.attempts + 1,
        )

        jobs.finish_job(claimed.pk, claimed.attempts, self.enrollment)

        submission.refresh_from_db()

        self.assertEqual(submission.status, Submission.Status.PROCESSING)
        self.assertIsNone(submission.enrollment)


class WorkerFailureTests(RecognitionJobTestMixin, TestCase):
    def test_unexpired_running_job_is_left_alone(self):
        self.create_processing_submission()
        jobs.claim_next_job()

        self.assertEqual(jobs.recover_expired_jobs(), 0)

    def test_crashed_workers_job_is_requeued(self):
        submission = self.create_processing_submission()

        claimed = jobs.claim_next_job()
        self.expire_lease(claimed)

        self.assertEqual(jobs.recover_expired_jobs(), 1)

        job = submission.recognition_jobs.get()

        self.assertEqual(job.status, RecognitionJob.Status.QUEUED)
        self.assertIsNone(job.lease_expires_at)
        self.assertIn("Worker stopped", job.last_error)

    def test_crashed_worker_late_result_is_discarded(self):
        submission = self.create_processing_submission()

        claimed = jobs.claim_next_job()
        self.expire_lease(claimed)
        jobs.recover_expired_jobs()

        jobs.finish_job(claimed.pk, claimed.attempts, self.enrollment)

        submission.refresh_from_db()

        self.assertEqual(submission.status, Submission.Status.PROCESSING)

    def test_timed_out_job_is_rerun_after_recovery(self):
        submission = self.create_processing_submission()

        claimed = jobs.claim_next_job()
        self.expire_lease(claimed)
        jobs.recover_expired_jobs()

        with patch(RECOGNIZE, return_value=self.enrollment):
            jobs.process_next_job()

        submission.refresh_from_db()
        job = submission.recognition_jobs.get()

        self.assertEqual(submission.status, Submission.Status.MATCHED)
        self.assertEqual(job.attempts, 2)

    def test_repeated_worker_crashes_fail_the_job(self):
        submission = self.create_processing_submission()

        for _ in range(3):
            claimed = jobs.claim_next_job()
            self.expire_lease(claimed)
            jobs.recover_expired_jobs()

        submission.refresh_from_db()
        job = submission.recognition_jobs.get()

        self.assertEqual(job.status, RecognitionJob.Status.FAILED)
        self.assertEqual(
            submission.status,
            Submission.Status.RECOGNITION_FAILED,
        )

    def test_restarted_worker_recovers_and_processes(self):
        submission = self.create_processing_submission()

        claimed = jobs.claim_next_job()
        self.expire_lease(claimed)

        output = StringIO()

        # TestCase runs inside a transaction; the worker's connection
        # cleanup would close the test's own connection.
        with patch(RECOGNIZE, return_value=self.enrollment), patch(
            "submissions.management.commands.run_recognition_worker"
            ".close_old_connections"
        ):
            call_command(
                "run_recognition_worker",
                "--once",
                stdout=output,
            )

        submission.refresh_from_db()

        self.assertIn("Recovered 1", output.getvalue())
        self.assertEqual(submission.status, Submission.Status.MATCHED)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadQueueTests(RecognitionJobTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def upload(self, name="script.pdf"):
        return self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": SimpleUploadedFile(
                    name,
                    b"fake pdf content",
                    content_type="application/pdf",
                ),
            },
            format="multipart",
        )

    def test_upload_returns_processing_without_running_recognition(self):
        with patch(RECOGNIZE) as mock_recognize:
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], Submission.Status.PROCESSING)
        self.assertEqual(
            response.data["recognition_job"]["status"],
            RecognitionJob.Status.QUEUED,
        )
        mock_recognize.assert_not_called()

    def test_failure_reason_hides_error_details(self):
        response = self.upload()

        with patch(
            RECOGNIZE,
            side_effect=FileNotFoundError("C:\\secret\\path.pdf"),
        ):
            jobs.process_next_job()

        detail = self.client.get(
            f"/api/submissions/{response.data['id']}/"
        )

        self.assertEqual(
            detail.data["recognition_job"]["failure_reason"],
            "FileNotFoundError",
        )
        self.assertNotIn("secret", str(detail.data))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RetryEndpointTests(RecognitionJobTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.submission = self.create_processing_submission()
        self.url = (
            f"/api/submissions/{self.submission.id}/retry-recognition/"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def fail_submission(self):
        self.submission.recognition_jobs.update(
            status=RecognitionJob.Status.FAILED,
        )
        Submission.objects.filter(pk=self.submission.pk).update(
            status=Submission.Status.RECOGNITION_FAILED,
        )

    def test_owner_can_retry_failed_submission(self):
        self.fail_submission()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], Submission.Status.PROCESSING)
        self.assertEqual(
            self.submission.recognition_jobs.filter(
                status=RecognitionJob.Status.QUEUED,
            ).count(),
            1,
        )

    def test_owner_can_retry_needs_verification_submission(self):
        with patch(RECOGNIZE, return_value=None):
            jobs.process_next_job()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], Submission.Status.PROCESSING)

    def test_duplicate_retry_is_idempotent(self):
        self.fail_submission()

        self.client.post(self.url)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(
            self.submission.recognition_jobs.filter(
                status__in=RecognitionJob.ACTIVE_STATUSES,
            ).count(),
            1,
        )

    def test_cannot_retry_matched_submission(self):
        with patch(RECOGNIZE, return_value=self.enrollment):
            jobs.process_next_job()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_user_cannot_retry(self):
        self.fail_submission()

        self.client.force_authenticate(user=self.other_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_retry(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReplacementUploadTests(RecognitionJobTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": SimpleUploadedFile(
                    "old.pdf",
                    b"old content",
                    content_type="application/pdf",
                ),
            },
            format="multipart",
        )
        self.submission = Submission.objects.get(pk=response.data["id"])

    def replace(self, name="new.pdf", **extra):
        return self.client.patch(
            f"/api/submissions/{self.submission.id}/",
            {
                "file": SimpleUploadedFile(
                    name,
                    b"new content",
                    content_type="application/pdf",
                ),
                **extra,
            },
            format="multipart",
        )

    def test_replacement_cancels_running_job_and_queues_new_one(self):
        claimed = jobs.claim_next_job()

        response = self.replace()

        self.submission.refresh_from_db()
        claimed.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(claimed.status, RecognitionJob.Status.CANCELLED)
        self.assertEqual(self.submission.original_filename, "new.pdf")
        self.assertEqual(
            self.submission.status,
            Submission.Status.PROCESSING,
        )
        self.assertEqual(
            self.submission.recognition_jobs.filter(
                status=RecognitionJob.Status.QUEUED,
            ).count(),
            1,
        )

    def test_cancelled_jobs_late_result_is_discarded(self):
        claimed = jobs.claim_next_job()

        self.replace()

        jobs.finish_job(claimed.pk, claimed.attempts, self.enrollment)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.status,
            Submission.Status.PROCESSING,
        )
        self.assertIsNone(self.submission.enrollment)

    def test_replacing_verified_submission_clears_enrollment(self):
        Submission.objects.filter(pk=self.submission.pk).update(
            enrollment=self.enrollment,
            status=Submission.Status.VERIFIED,
        )

        self.replace(enrollment=self.enrollment.id)

        self.submission.refresh_from_db()

        self.assertIsNone(self.submission.enrollment)
        self.assertEqual(
            self.submission.status,
            Submission.Status.PROCESSING,
        )

    def test_cannot_replace_marked_submission(self):
        Submission.objects.filter(pk=self.submission.pk).update(
            enrollment=self.enrollment,
            status=Submission.Status.MARKED,
        )

        response = self.replace()

        self.submission.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.submission.status, Submission.Status.MARKED)
        self.assertEqual(self.submission.original_filename, "old.pdf")

    def test_other_user_cannot_replace(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.replace()

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
