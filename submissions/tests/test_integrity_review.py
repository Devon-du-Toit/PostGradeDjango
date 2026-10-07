import json
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.lifecycle import withdraw_enrollment
from students.models import Enrollment, Student
from submissions.jobs import finish_job
from submissions.models import RecognitionJob, Submission


class IntegrityReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="integrity@example.invalid", password="ExamplePassword!42"
        )
        self.other = User.objects.create_user(
            email="other@example.invalid", password="ExamplePassword!42"
        )
        self.course = Course.objects.create(
            owner=self.user, code="C101", name="Synthetic", year=2026, semester=1
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Synthetic"
        )
        self.student = Student.objects.create(
            owner=self.user,
            student_number="00123456",
            first_name="Test",
            last_name="Student",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course, student=self.student
        )
        self.submission = Submission.objects.create(
            assessment=self.assessment,
            file="original.pdf",
            original_filename="original.pdf",
            status="processing",
        )

    def test_normal_orm_saves_enforce_membership_and_owner_transfers(self):
        foreign = Student.objects.create(owner=self.other, student_number="00123456")
        with self.assertRaises(ValidationError):
            Enrollment.objects.create(course=self.course, student=foreign)
        self.student.owner = self.other
        with self.assertRaises(ValidationError):
            self.student.save()
        self.course.owner = self.other
        with self.assertRaises(ValidationError):
            self.course.save()
        another = Course.objects.create(
            owner=self.user, code="C102", name="Other", year=2026, semester=1
        )
        enrollment = Enrollment.objects.create(
            course=another, student=Student.objects.get(pk=self.student.pk)
        )
        self.submission.enrollment = enrollment
        with self.assertRaises(ValidationError):
            self.submission.save()

    def test_referenced_enrollment_cannot_silently_reassign_verified_identity(self):
        self.submission.record_status_change(
            self.user, "verified", new_enrollment=self.enrollment
        )
        self.enrollment.student = Student.objects.create(
            owner=self.user, student_number="00234567"
        )
        with self.assertRaises(ValidationError):
            self.enrollment.save()

    def test_audit_snapshot_survives_contact_edits_and_enrollment_withdrawal(self):
        audit = self.submission.record_status_change(
            self.user, "verified", new_enrollment=self.enrollment
        )
        identity = dict(audit.new_identity)
        self.assertEqual(identity["student_number"], "00123456")
        self.student.student_number = "00999999"
        self.student.save()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.enrollment.delete()
        withdrawn = withdraw_enrollment(
            self.enrollment.pk, self.user, self.enrollment.version, "Student withdrew"
        )
        audit.refresh_from_db()
        self.assertEqual(audit.new_enrollment_id, self.enrollment.pk)
        self.assertEqual(audit.new_identity, identity)
        self.assertIsNotNone(withdrawn.withdrawn_at)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.enrollment_id, self.enrollment.pk)
        self.assertEqual(self.submission.status, "verified")
        self.assertFalse(
            Submission.objects.active().filter(pk=self.submission.pk).exists()
        )

    def test_existing_audit_identity_cannot_be_rewritten(self):
        audit = self.submission.record_status_change(
            self.user, "verified", new_enrollment=self.enrollment
        )
        audit.new_identity = {"student_number": "changed"}
        with self.assertRaises(ValidationError):
            audit.save()
        audit.refresh_from_db()
        self.assertEqual(audit.new_identity["student_number"], "00123456")

    def test_deleted_recognition_suggestion_finishes_as_manual_verification(self):
        job = RecognitionJob.objects.create(
            submission=self.submission, status="running", attempts=1
        )
        cached = Enrollment.objects.get(pk=self.enrollment.pk)
        self.enrollment.delete()
        finish_job(job.pk, 1, cached)
        job.refresh_from_db()
        self.submission.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(self.submission.status, "needs_verification")
        self.assertIsNone(self.submission.enrollment_id)
        self.assertEqual(self.submission.audit_entries.get().new_identity, {})

    def test_other_course_recognition_suggestion_is_rejected(self):
        course = Course.objects.create(
            owner=self.user, code="C102", name="Other", year=2026, semester=1
        )
        enrollment = Enrollment.objects.create(course=course, student=self.student)
        job = RecognitionJob.objects.create(
            submission=self.submission, status="running", attempts=1
        )
        finish_job(job.pk, 1, enrollment)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, "needs_verification")
        self.assertIsNone(self.submission.enrollment_id)

    def test_read_only_integrity_command_detects_bulk_bypassed_validation(self):
        foreign = Student.objects.create(owner=self.other, student_number="99999999")
        # An operator can inspect intermediate data in an explicitly deferred
        # repair transaction; incompatible data still cannot commit.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS pg51_enrollment_student_owner DEFERRED")
        Enrollment.objects.bulk_create(
            [Enrollment(course=self.course, student=foreign)]
        )
        before = Enrollment.objects.count()
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "audit_database_integrity", fail_on_invalid=True, stdout=output
            )
        self.assertEqual(json.loads(output.getvalue())["invalid_enrollment_owners"], 1)
        self.assertEqual(Enrollment.objects.count(), before)
        Enrollment.objects.filter(student=foreign).delete()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS pg51_enrollment_student_owner IMMEDIATE")

    def test_submission_and_queue_query_counts_do_not_grow_with_page_size(self):
        Submission.objects.bulk_create(
            [
                Submission(
                    assessment=self.assessment,
                    original_filename=f"script-{i}.pdf",
                    status="matched",
                    enrollment=self.enrollment,
                )
                for i in range(100)
            ]
        )
        client = APIClient()
        client.force_authenticate(self.user)
        for path in ("/api/submissions/", "/api/submissions/verification-queue/"):
            counts = []
            for page_size in (1, 25, 100):
                with CaptureQueriesContext(connection) as queries:
                    response = client.get(path, {"page_size": page_size})
                self.assertEqual(response.status_code, 200)
                counts.append(len(queries))
            self.assertEqual(counts, [5, 5, 5])
