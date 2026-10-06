from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.models import RecognitionAttempt, RecognitionJob, SubmissionAudit
from submissions.tests.helpers import TemporaryMediaMixin, make_pdf, make_png
from submissions import jobs
from distribution import dispatch
from students.csv_import import CSVFileError, apply_import_plan, build_import_plan


def listed_ids(response):
    """IDs from a list response, whether or not it is paginated."""
    data = response.data
    items = data["results"] if isinstance(data, dict) else data
    return [item["id"] for item in items]


class ArchiveTests(TemporaryMediaMixin, TestCase):
    """DELETE archives courses and assessments; recorded data is kept."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="teacher@example.com",
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
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_submission(self, assessment=None):
        return Submission.objects.create(
            assessment=assessment or self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

    def assessment_url(self):
        return reverse("assessment-detail", kwargs={"pk": self.assessment.pk})

    def course_url(self):
        return reverse("course-detail", kwargs={"pk": self.course.pk})

    def assessment_list_url(self):
        return reverse(
            "course-assessment-list-create",
            kwargs={"course_id": self.course.pk},
        )

    # --- Assessments ---

    def test_deleting_an_archived_assessment_again_is_404(self):
        self.client.delete(self.assessment_url())

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_teacher_cannot_archive_assessment(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.archived_at)

    # --- Courses ---

    def test_assessment_of_archived_course_is_hidden(self):
        self.client.delete(self.course_url())

        response = self.client.get(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_teacher_cannot_archive_course(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.course.refresh_from_db()
        self.assertIsNone(self.course.archived_at)

    def archive_parent(self, parent):
        return self.client.delete(
            self.course_url() if parent == "course" else self.assessment_url()
        )

    def test_archived_parent_blocks_submission_reads_and_actions(self):
        submission = self.make_submission()
        submission.status = Submission.Status.NEEDS_VERIFICATION
        submission.save(update_fields=["status"])
        attempt = RecognitionAttempt.objects.create(
            submission=submission,
            method=RecognitionAttempt.Method.OCR,
            outcome=RecognitionAttempt.Outcome.NO_MATCH,
        )
        attempt.region_image.save("crop.png", ContentFile(make_png()))

        for parent in ["assessment", "course"]:
            with self.subTest(parent=parent):
                self.archive_parent(parent)
                base = f"/api/submissions/{submission.pk}/"
                for method, path, data in [
                    ("get", base, None),
                    ("get", base + "file/", None),
                    ("get", base + "recognition-image/", None),
                    ("patch", base, {"version": 0}),
                    ("delete", base, None),
                    ("post", base + "verify/", {"enrollment": self.enrollment.pk}),
                    ("post", base + "mark/", {"mark": 40}),
                    ("post", base + "retry-recognition/", {}),
                ]:
                    with self.subTest(method=method, path=path):
                        response = getattr(self.client, method)(
                            path, data, format="json"
                        )
                        self.assertEqual(response.status_code, 404)
                for path in [
                    "/api/submissions/",
                    "/api/submissions/verification-queue/",
                ]:
                    self.assertNotIn(submission.pk, listed_ids(self.client.get(path)))
                self.assertEqual(Submission.objects.count(), 1)
                self.assertTrue(submission.file.storage.exists(submission.file.name))
                self.assertTrue(
                    attempt.region_image.storage.exists(attempt.region_image.name)
                )
                self.assertFalse(SubmissionAudit.objects.exists())
                Assessment.objects.filter(pk=self.assessment.pk).update(
                    archived_at=None
                )

    def test_upload_to_archived_assessment_or_course_is_rejected(self):
        for parent in ["assessment", "course"]:
            with self.subTest(parent=parent):
                self.archive_parent(parent)
                response = self.client.post(
                    "/api/submissions/",
                    {
                        "assessment": self.assessment.pk,
                        "file": SimpleUploadedFile("test.pdf", make_pdf()),
                    },
                    format="multipart",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("assessment", response.data)
                self.assertFalse(Submission.objects.exists())
                self.assertFalse(RecognitionJob.objects.exists())
                Assessment.objects.filter(pk=self.assessment.pk).update(
                    archived_at=None
                )

    def test_archived_course_blocks_csv_and_enrollment_creation(self):
        self.client.delete(self.course_url())
        response = self.client.post(
            f"/api/courses/{self.course.pk}/import-students/",
            {
                "file": SimpleUploadedFile(
                    "class.csv",
                    b"student_number,first_name,last_name,email\n222,New,Student,new@example.com\n",
                )
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Student.objects.count(), 1)
        for data in [None, {"search": "Alice"}]:
            self.assertEqual(
                self.client.get(
                    f"/api/courses/{self.course.pk}/students/",
                    data,
                ).status_code,
                404,
            )
        self.assertNotIn(
            self.enrollment.pk, listed_ids(self.client.get("/api/enrollments/"))
        )
        response = self.client.post(
            "/api/enrollments/",
            {"course": self.course.pk, "student": self.student.pk},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_csv_plan_validated_before_archive_cannot_be_applied(self):
        plan = build_import_plan(
            self.user,
            SimpleUploadedFile(
                "class.csv",
                b"student_number,first_name,last_name,email\n222,New,Student,new@example.com\n",
            ),
            serializer_context={"request": type("Request", (), {"user": self.user})()},
        )
        self.course.archive()
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.user, self.course, plan)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_filters_reject_archived_course_and_assessment_ids(self):
        self.assessment.archive()
        self.assertEqual(
            self.client.get(
                "/api/submissions/", {"assessment": self.assessment.pk}
            ).status_code,
            400,
        )
        self.course.archive()
        for path in [
            "/api/students/",
            "/api/enrollments/",
            "/api/submissions/",
            "/api/dashboard/assessments/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(path, {"course": self.course.pk}).status_code, 400
                )

    def test_archive_cancels_recognition_and_preserves_records(self):
        submission = self.make_submission()
        submission.status = Submission.Status.PROCESSING
        submission.save(update_fields=["status"])
        job = jobs.enqueue_recognition(submission)
        audit = SubmissionAudit.objects.create(
            submission=submission,
            previous_status="uploaded",
            new_status="processing",
        )
        self.assessment.archive()
        job.refresh_from_db()
        self.assertEqual(job.status, RecognitionJob.Status.CANCELLED)
        self.assertIsNotNone(job.finished_at)
        self.assertTrue(SubmissionAudit.objects.filter(pk=audit.pk).exists())
        self.assertIsNone(jobs.claim_next_job())
        with self.assertRaises(ValidationError):
            jobs.retry_recognition(submission.pk)
        with self.assertRaises(ValidationError):
            jobs.enqueue_recognition(submission)
