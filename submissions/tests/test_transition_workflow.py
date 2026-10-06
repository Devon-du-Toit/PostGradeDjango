from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from submissions.tests.test_audit import SubmissionAuditTests
from submissions.tests.helpers import TemporaryMediaMixin, make_pdf
from submissions.models import Submission, RecognitionJob
from submissions.jobs import finish_job, retry_recognition, fail_job


class TransitionWorkflowTests(TemporaryMediaMixin, TestCase):
    _make_submission = SubmissionAuditTests._make_submission
    _enrollment = SubmissionAuditTests._enrollment

    def setUp(self):
        SubmissionAuditTests.setUp(self)
        self.enrollment = self._enrollment()
        self.submission = self._make_submission()
        Submission.objects.filter(pk=self.submission.pk).update(
            status="needs_verification"
        )
        self.submission.refresh_from_db()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def verify(self, **extra):
        return self.client.post(
            f"/api/submissions/{self.submission.pk}/verify/",
            {"enrollment": self.enrollment.pk, **extra},
            format="json",
        )

    def test_initial_verification_and_stale_confirmation(self):
        self.assertEqual(self.verify(version=0).status_code, 200)
        self.assertEqual(self.verify(version=0).status_code, 400)
        self.assertEqual(self.submission.audit_entries.count(), 1)

    def test_reassignment_requires_explicit_correction(self):
        self.verify()
        other = self._enrollment_other()
        response = self.client.post(
            f"/api/submissions/{self.submission.pk}/verify/",
            {"enrollment": other.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        url = f"/api/submissions/{self.submission.pk}/correct/"
        for payload in (
            {"enrollment": other.pk},
            {"enrollment": other.pk, "version": 1, "reason": " "},
            {"enrollment": other.pk, "version": 0, "reason": "Wrong student"},
        ):
            self.assertEqual(
                self.client.post(url, payload, format="json").status_code, 400
            )
        response = self.client.post(
            url,
            {"enrollment": other.pk, "version": 1, "reason": "Wrong student selected"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        audit = self.submission.audit_entries.first()
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.previous_enrollment, self.enrollment)
        self.assertEqual(audit.new_enrollment, other)
        self.assertEqual(audit.reason, "Wrong student selected")
        self.assertIsNotNone(audit.timestamp)
        self.assertEqual(
            self.client.post(
                url,
                {
                    "enrollment": self.enrollment.pk,
                    "version": 1,
                    "reason": "Stale correction",
                },
                format="json",
            ).status_code,
            400,
        )

    def _enrollment_other(self):
        from students.models import Enrollment, Student

        student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Other",
            last_name="Student",
            email="other@example.invalid",
        )
        return Enrollment.objects.create(course=self.course, student=student)

    def test_malformed_transition_payload_is_rejected(self):
        for value in ("garbage", [], {}, None):
            response = self.client.post(
                f"/api/submissions/{self.submission.pk}/verify/",
                {"enrollment": value},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.verify(version=-1).status_code, 400)
        self.assertFalse(self.submission.audit_entries.exists())

    def test_upload_and_replacement_record_actor_and_identity_reset(self):
        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.pk,
                "file": SimpleUploadedFile("test.pdf", make_pdf()),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        submission = Submission.objects.get(pk=response.data["id"])
        audit = submission.audit_entries.get()
        self.assertIsNone(audit.previous_status)
        self.assertEqual(audit.new_status, "processing")
        self.assertEqual(audit.actor, self.user)
        submission.record_status_change(
            self.user, "verified", new_enrollment=self.enrollment
        )
        response = self.client.patch(
            f"/api/submissions/{submission.pk}/",
            {"file": SimpleUploadedFile("replacement.pdf", make_pdf()), "version": 1},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        audit = submission.audit_entries.first()
        self.assertEqual(audit.previous_status, "verified")
        self.assertEqual(audit.previous_enrollment, self.enrollment)
        self.assertIsNone(audit.new_enrollment)
        self.assertEqual(audit.new_status, "processing")
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(response.data["version"], 2)

    def test_retry_and_worker_share_versioned_audit(self):
        Submission.objects.filter(pk=self.submission.pk).update(
            enrollment=self.enrollment
        )
        retry_recognition(self.submission.pk, actor=self.user, expected_version=0)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.version, 1)
        self.assertIsNone(self.submission.enrollment)
        job = self.submission.recognition_jobs.get()
        job.status = "running"
        job.attempts = 1
        job.save()
        finish_job(job.pk, 1, self.enrollment)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.version, 2)
        audit = self.submission.audit_entries.first()
        self.assertIsNone(audit.actor)
        self.assertEqual(audit.new_enrollment, self.enrollment)
        self.assertEqual(audit.new_status, "matched")
        # Old worker attempt and repeated completion cannot change the row.
        finish_job(job.pk, 1, None)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.version, 2)
        self.assertEqual(self.submission.audit_entries.count(), 2)

    def test_failed_worker_versions_failure_and_preserves_verified_state(self):
        retry_recognition(self.submission.pk, actor=self.user)
        job = self.submission.recognition_jobs.get()
        job.status = "running"
        job.attempts = job.max_attempts
        job.save()
        fail_job(job.pk, job.attempts, RuntimeError("failed"))
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, "recognition_failed")
        self.assertEqual(self.submission.version, 2)
        self.assertEqual(
            self.submission.audit_entries.first().new_status, "recognition_failed"
        )

    def test_stale_retry_and_stale_model_transition_do_not_write(self):
        retry_recognition(self.submission.pk, actor=self.user, expected_version=0)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            retry_recognition(self.submission.pk, actor=self.user, expected_version=0)
        with self.assertRaises(ValueError):
            self.submission.record_status_change(
                self.user, "verified", expected_version=0
            )
        self.assertEqual(self.submission.audit_entries.count(), 1)


class CompetingCorrectionsTests(TransactionTestCase):
    def setUp(self):
        fixtures = SubmissionAuditTests()
        fixtures.setUp()
        self.user = fixtures.user
        self.submission = fixtures._make_submission()
        self.enrollment = fixtures._enrollment()
        Submission.objects.filter(pk=self.submission.pk).update(
            status="verified", enrollment=self.enrollment
        )
        from students.models import Enrollment, Student

        self.other = Enrollment.objects.create(
            course=fixtures.course,
            student=Student.objects.create(
                owner=self.user,
                student_number="87654321",
                first_name="Other",
                last_name="Student",
            ),
        )

    def test_only_one_correction_can_consume_a_version(self):
        from threading import Barrier
        from submissions.verification import verify_submission
        from django.core.exceptions import ValidationError

        barrier = Barrier(2)

        def correct():
            close_old_connections()
            try:
                submission = Submission.objects.get(pk=self.submission.pk)
                barrier.wait(timeout=10)
                verify_submission(
                    submission,
                    self.other,
                    self.user,
                    correction=True,
                    expected_version=0,
                    reason="Concurrent correction",
                )
                return "accepted"
            except ValidationError:
                return "stale"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: correct(), range(2)))
        self.assertCountEqual(results, ["accepted", "stale"])
        self.assertEqual(self.submission.audit_entries.count(), 1)
