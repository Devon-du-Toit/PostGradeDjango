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
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.models import RecognitionAttempt, RecognitionJob, SubmissionAudit
from submissions.tests.helpers import TemporaryMediaMixin, make_pdf, make_png
from submissions import jobs
from distribution import dispatch
from distribution.models import ResultEmail
from distribution.services import approve_email, retry_email, schedule_result_email
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
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
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

    def make_result(self, assessment=None):
        return Result.objects.create(
            assessment=assessment or self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

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

    def gradebook_url(self):
        return reverse("course-gradebook", kwargs={"course_id": self.course.pk})

    def statistics_url(self):
        return reverse(
            "assessment-statistics",
            kwargs={"pk": self.assessment.pk},
        )

    # --- Assessments ---

    def test_delete_assessment_archives_it_and_keeps_data(self):
        self.make_result()
        self.make_submission()

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assessment.refresh_from_db()
        self.assertIsNotNone(self.assessment.archived_at)
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(Submission.objects.count(), 1)

    def test_archived_assessment_is_hidden(self):
        self.client.delete(self.assessment_url())

        detail = self.client.get(self.assessment_url())
        listing = self.client.get(self.assessment_list_url())
        statistics = self.client.get(self.statistics_url())

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(self.assessment.pk, listed_ids(listing))
        self.assertEqual(statistics.status_code, status.HTTP_404_NOT_FOUND)

    def test_archived_assessment_is_left_out_of_gradebook(self):
        second = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )
        self.make_result()
        self.client.delete(self.assessment_url())

        response = self.client.get(self.gradebook_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [
            item["assessment"]
            for item in response.data["students"][0]["assessments"]
        ]
        self.assertEqual(ids, [second.pk])

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

    def test_delete_course_archives_it_and_keeps_data(self):
        self.make_result()
        self.make_submission()

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.course.refresh_from_db()
        self.assertIsNotNone(self.course.archived_at)
        self.assertTrue(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(Submission.objects.count(), 1)

    def test_archived_course_is_hidden(self):
        self.client.delete(self.course_url())

        detail = self.client.get(self.course_url())
        listing = self.client.get(reverse("course-list-create"))
        assessments = self.client.get(self.assessment_list_url())
        gradebook = self.client.get(self.gradebook_url())

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(self.course.pk, listed_ids(listing))
        self.assertEqual(assessments.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(gradebook.status_code, status.HTTP_404_NOT_FOUND)

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

    def test_archived_assessment_is_left_out_of_course_grade(self):
        second = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )
        self.make_result()  # 40 out of 50 = 80%
        Result.objects.create(
            assessment=second,
            enrollment=self.enrollment,
            mark=Decimal("50.00"),  # 50%
        )
        self.client.delete(self.assessment_url())

        response = self.client.get(self.gradebook_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["students"][0]["course_percentage"],
            Decimal("50.00"),
        )

    def archive_parent(self, parent):
        return self.client.delete(
            self.course_url() if parent == "course" else self.assessment_url()
        )

    def test_archived_parent_blocks_submission_reads_and_actions(self):
        submission = self.make_submission()
        submission.status = Submission.Status.NEEDS_VERIFICATION
        submission.save(update_fields=["status"])
        attempt = RecognitionAttempt.objects.create(
            submission=submission, method=RecognitionAttempt.Method.OCR,
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
                        response = getattr(self.client, method)(path, data, format="json")
                        self.assertEqual(response.status_code, 404)
                for path in ["/api/submissions/", "/api/submissions/verification-queue/"]:
                    self.assertNotIn(submission.pk, listed_ids(self.client.get(path)))
                self.assertEqual(Submission.objects.count(), 1)
                self.assertTrue(submission.file.storage.exists(submission.file.name))
                self.assertTrue(attempt.region_image.storage.exists(attempt.region_image.name))
                self.assertFalse(SubmissionAudit.objects.exists())
                Assessment.objects.filter(pk=self.assessment.pk).update(archived_at=None)

    def test_upload_to_archived_assessment_or_course_is_rejected(self):
        for parent in ["assessment", "course"]:
            with self.subTest(parent=parent):
                self.archive_parent(parent)
                response = self.client.post(
                    "/api/submissions/",
                    {"assessment": self.assessment.pk,
                     "file": SimpleUploadedFile("test.pdf", make_pdf())},
                    format="multipart",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("assessment", response.data)
                self.assertFalse(Submission.objects.exists())
                self.assertFalse(RecognitionJob.objects.exists())
                Assessment.objects.filter(pk=self.assessment.pk).update(archived_at=None)

    def test_archived_course_blocks_csv_and_enrollment_creation(self):
        self.client.delete(self.course_url())
        response = self.client.post(
            f"/api/courses/{self.course.pk}/import-students/",
            {"file": SimpleUploadedFile("class.csv", b"student_number,first_name,last_name,email\n222,New,Student,new@example.com\n")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Student.objects.count(), 1)
        for data in [None, {"search": "Alice"}]:
            self.assertEqual(self.client.get(
                f"/api/courses/{self.course.pk}/students/", data,
            ).status_code, 404)
        self.assertNotIn(self.enrollment.pk, listed_ids(self.client.get("/api/enrollments/")))
        response = self.client.post(
            "/api/enrollments/", {"course": self.course.pk, "student": self.student.pk},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_csv_plan_validated_before_archive_cannot_be_applied(self):
        plan = build_import_plan(
            self.user,
            SimpleUploadedFile("class.csv", b"student_number,first_name,last_name,email\n222,New,Student,new@example.com\n"),
            serializer_context={"request": type("Request", (), {"user": self.user})()},
        )
        self.course.archive()
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.user, self.course, plan)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_dashboard_excludes_archived_assessments_and_courses(self):
        self.course.year = 2026
        self.course.save(update_fields=["year"])
        submission = self.make_submission()
        submission.status = Submission.Status.NEEDS_VERIFICATION
        submission.save(update_fields=["status"])
        self.make_result()
        self.assessment.archive()
        response = self.client.get("/api/dashboard/stats/")
        self.assertEqual(response.data["pending_verifications"], 0)
        self.assertEqual(sum(response.data["submissions_by_status"].values()), 0)
        self.assertNotIn(self.assessment.pk, listed_ids(self.client.get("/api/dashboard/assessments/")))
        self.course.archive()
        self.assertEqual(self.client.get("/api/dashboard/stats/").data["active_courses"], 0)

    def test_filters_reject_archived_course_and_assessment_ids(self):
        self.assessment.archive()
        self.assertEqual(self.client.get("/api/submissions/", {"assessment": self.assessment.pk}).status_code, 400)
        self.course.archive()
        for path in ["/api/students/", "/api/enrollments/", "/api/submissions/", "/api/dashboard/assessments/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, {"course": self.course.pk}).status_code, 400)

    def test_archived_result_emails_are_hidden_and_cannot_be_released(self):
        result = self.make_result()
        email = schedule_result_email(result)
        for parent in ["assessment", "course"]:
            with self.subTest(parent=parent):
                self.archive_parent(parent)
                base = f"/api/result-emails/{email.pk}/"
                self.assertEqual(self.client.get(base).status_code, 404)
                for path in [base + "approve/", base + "retry/",
                             f"/api/assessments/{self.assessment.pk}/result-emails/approve/"]:
                    self.assertEqual(self.client.post(path, {}).status_code, 404)
                self.assertEqual(self.client.get(
                    f"/api/assessments/{self.assessment.pk}/result-emails/",
                ).status_code, 404)
                with self.assertRaises(ValidationError):
                    approve_email(email.pk, self.user)
                with self.assertRaises(ValidationError):
                    retry_email(email.pk)
                self.assertTrue(Result.objects.filter(pk=result.pk).exists())
                self.assertTrue(ResultEmail.objects.filter(pk=email.pk).exists())
                Assessment.objects.filter(pk=self.assessment.pk).update(archived_at=None)

    def test_archive_cancels_recognition_and_preserves_records(self):
        submission = self.make_submission()
        submission.status = Submission.Status.PROCESSING
        submission.save(update_fields=["status"])
        job = jobs.enqueue_recognition(submission)
        audit = SubmissionAudit.objects.create(
            submission=submission, previous_status="uploaded", new_status="processing",
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

    def test_running_recognition_cannot_apply_result_after_archive(self):
        submission = self.make_submission()
        submission.status = Submission.Status.PROCESSING
        submission.save(update_fields=["status"])
        jobs.enqueue_recognition(submission)
        claimed = jobs.claim_next_job()
        self.course.archive()
        jobs.finish_job(claimed.pk, claimed.attempts, self.enrollment)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PROCESSING)
        self.assertIsNone(submission.enrollment)
        self.assertFalse(SubmissionAudit.objects.exists())

    def test_archive_suppresses_queued_email_but_keeps_sent_history(self):
        result = self.make_result()
        queued = schedule_result_email(result)
        sent = ResultEmail.objects.create(
            result=result, result_version=1, idempotency_key="sent-history",
            recipient=self.student.email, subject="Already sent", body="Result",
            status=ResultEmail.Status.SENT,
        )
        self.course.archive()
        queued.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(queued.status, ResultEmail.Status.SUPERSEDED)
        self.assertEqual(sent.status, ResultEmail.Status.SENT)
        with patch("distribution.dispatch.EmailMessage.send") as send:
            self.assertFalse(dispatch.process_next_email())
        send.assert_not_called()
        with self.assertRaises(ValidationError):
            schedule_result_email(result)

    def test_claimed_email_is_not_sent_if_archive_precedes_delivery(self):
        email = schedule_result_email(self.make_result())
        claimed = dispatch.claim_next_email()
        self.assessment.archive()
        with patch("distribution.dispatch.EmailMessage.send") as send:
            dispatch.deliver_email(claimed, claimed.attempts)
        send.assert_not_called()
        email.refresh_from_db()
        self.assertEqual(email.status, ResultEmail.Status.SUPERSEDED)

    def test_archiving_one_assessment_keeps_other_workflows_active(self):
        other = Assessment.objects.create(
            course=self.course, name="Still active", max_mark=50, weight=20,
        )
        submission = self.make_submission(other)
        submission.status = Submission.Status.PROCESSING
        submission.save(update_fields=["status"])
        job = jobs.enqueue_recognition(submission)
        email = schedule_result_email(self.make_result(other))

        self.assessment.archive()

        job.refresh_from_db()
        email.refresh_from_db()
        self.assertEqual(job.status, RecognitionJob.Status.QUEUED)
        self.assertEqual(email.status, ResultEmail.Status.QUEUED)
        self.assertEqual(self.client.get(f"/api/submissions/{submission.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/result-emails/{email.pk}/").status_code, 200)
        self.assertIn(other.pk, listed_ids(self.client.get(self.assessment_list_url())))
