from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from distribution.dispatch import claim_next_email, deliver_email
from distribution.services import schedule_script_email
from students.csv_import import CSVFileError, apply_import_plan, build_import_plan
from students.lifecycle import archive_student, withdraw_enrollment
from students.models import Enrollment, Student
from submissions.jobs import claim_next_job, finish_job
from submissions.models import Submission
from submissions.services import create_submission, replace_submission
from submissions.tests.helpers import TemporaryMediaMixin, make_pdf
from submissions.tests.test_qr_grouping import paper, qr
from submissions.verification import verify_submission


class RetentionFixtures:
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.invalid", password="SyntheticPassword123"
        )
        self.other = User.objects.create_user(
            email="other@example.invalid", password="SyntheticPassword123"
        )
        self.course = Course.objects.create(
            owner=self.user, code="CMPG211", name="Synthetic", year=2023, semester=1
        )
        self.assessment = Assessment.objects.create(course=self.course, name="Test")
        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Original",
            last_name="Name",
            email="student@example.invalid",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course, student=self.student
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self):
        return create_submission(
            dict(
                assessment=self.assessment,
                file=SimpleUploadedFile("synthetic.pdf", make_pdf()),
            ),
            self.user,
        )

    def verified(self):
        script = self.upload()
        verify_submission(
            script, self.enrollment, self.user, expected_version=script.version
        )
        return script


class RetentionTests(RetentionFixtures, TemporaryMediaMixin, TestCase):
    def test_newer_verified_script_replaces_current_and_keeps_older_history(self):
        old = self.verified()
        email = schedule_script_email(old)
        new = self.upload()
        self.assertTrue(Submission.objects.active().filter(pk=old.pk).exists())
        verify_submission(new, self.enrollment, self.user, expected_version=new.version)
        old.refresh_from_db()
        email.refresh_from_db()
        self.assertEqual(old.status, "verified")
        self.assertEqual(old.superseded_by_id, new.pk)
        self.assertEqual(email.status, "superseded")
        self.assertEqual(
            list(
                Submission.objects.active()
                .filter(status="verified")
                .values_list("pk", flat=True)
            ),
            [new.pk],
        )
        self.assertTrue(old.file.storage.exists(old.file.name))
        self.assertTrue(
            old.audit_entries.filter(
                reason="Replaced by newer verified script"
            ).exists()
        )

    def test_older_upload_cannot_replace_newer_verified_script(self):
        old = self.upload()
        current = self.verified()
        with self.assertRaises(ValidationError):
            verify_submission(old, self.enrollment, self.user)
        self.assertTrue(
            Submission.objects.active()
            .filter(pk=current.pk, status="verified")
            .exists()
        )

    def test_replacement_retains_private_original_bytes_and_identity(self):
        script = self.verified()
        old_name = script.file.name
        old_version = script.version
        self.student.first_name = "Renamed"
        self.student.student_number = "99999999"
        self.student.save()
        script = replace_submission(
            script,
            dict(
                version=script.version,
                file=SimpleUploadedFile("replacement.pdf", make_pdf(2)),
            ),
            self.user,
        )
        revision = script.file_revisions.filter(file=old_name, status="verified").get()
        self.assertEqual(revision.version, old_version)
        self.assertEqual(revision.student_identity["student_number"], "12345678")
        self.assertEqual(revision.student_identity["first_name"], "Original")
        self.assertTrue(script.file.storage.exists(old_name))
        self.assertNotEqual(script.file.name, old_name)
        revision.original_filename = "changed.pdf"
        with self.assertRaises(ValidationError):
            revision.save()

    def test_archive_keeps_files_audits_and_owner_only_history(self):
        script = self.verified()
        version = script.version
        self.assertEqual(
            self.client.delete(
                f"/api/submissions/{script.pk}/",
                dict(version=version, reason="Retain old test"),
                format="json",
            ).status_code,
            204,
        )
        script.refresh_from_db()
        self.assertIsNotNone(script.archived_at)
        self.assertEqual(
            self.client.get(f"/api/submissions/{script.pk}/").status_code, 404
        )
        response = self.client.get(
            "/api/submissions/history/", {"assessment": self.assessment.pk}
        )
        row = response.data["results"][0]
        self.assertEqual(row["student_identity"]["student_number"], "12345678")
        self.assertTrue(row["file_revisions"])
        self.assertTrue(row["audit_entries"])
        self.assertEqual(row["audit_entries"][0]["actor_email"], self.user.email)
        url = row["file_revisions"][0]["download_url"]
        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Cache-Control"], "private, no-store")
        self.assertIn("Authorization", download["Vary"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(self.user)
        self.assessment.archive()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_class_withdrawal_preserves_other_membership_and_blocks_delivery(self):
        script = self.verified()
        email = schedule_script_email(script)
        other_course = Course.objects.create(
            owner=self.user, code="OTHER", name="Other", year=2023, semester=1
        )
        other_membership = Enrollment.objects.create(
            course=other_course, student=self.student
        )
        withdrawn = withdraw_enrollment(
            self.enrollment.pk, self.user, self.enrollment.version, "Left this class"
        )
        self.assertIsNotNone(withdrawn.withdrawn_at)
        self.assertTrue(
            Enrollment.objects.active().filter(pk=other_membership.pk).exists()
        )
        self.assertFalse(Submission.objects.active().filter(pk=script.pk).exists())
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")
        self.assertIsNone(claim_next_email())
        restored = withdraw_enrollment(
            withdrawn.pk, self.user, withdrawn.version, "Returned", restore=True
        )
        self.assertIsNone(restored.withdrawn_at)
        self.assertTrue(Submission.objects.active().filter(pk=script.pk).exists())
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")

    def test_claimed_email_is_rechecked_after_withdrawal(self):
        script = self.verified()
        schedule_script_email(script)
        claimed = claim_next_email()
        withdraw_enrollment(
            self.enrollment.pk, self.user, self.enrollment.version, "Left class"
        )
        with patch("distribution.dispatch.EmailMessage.send") as send:
            deliver_email(claimed, claimed.attempts)
        send.assert_not_called()
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, "superseded")

    def test_claimed_recognition_cannot_restore_withdrawn_identity(self):
        script = self.upload()
        job = claim_next_job()
        withdraw_enrollment(
            self.enrollment.pk, self.user, self.enrollment.version, "Left class"
        )
        finish_job(job.pk, job.attempts, self.enrollment)
        job.refresh_from_db()
        script.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(script.status, "needs_verification")
        self.assertIsNone(script.enrollment_id)

    def test_global_student_archive_keeps_keys_and_explicit_restore(self):
        script = self.verified()
        student = archive_student(
            self.student.pk, self.user, self.student.version, "Contact retired"
        )
        self.assertIsNotNone(student.archived_at)
        self.enrollment.refresh_from_db()
        self.assertIsNotNone(self.enrollment.withdrawn_at)
        self.assertTrue(Submission.objects.filter(pk=script.pk).exists())
        self.assertEqual(
            self.client.post(
                "/api/students/",
                dict(
                    student_number="12345678",
                    first_name="Replacement",
                    last_name="Name",
                    email="new@example.invalid",
                ),
            ).status_code,
            400,
        )
        student = archive_student(
            student.pk, self.user, student.version, "Contact returned", restore=True
        )
        self.assertIsNone(student.archived_at)
        self.enrollment.refresh_from_db()
        self.assertIsNotNone(self.enrollment.withdrawn_at)
        with self.assertRaises(ValidationError):
            withdraw_enrollment(
                self.enrollment.pk, self.user, 0, "Stale restore", restore=True
            )

    def test_csv_never_restores_withdrawn_membership(self):
        withdraw_enrollment(self.enrollment.pk, self.user, 0, "Left class")
        raw = b"student_number,first_name,last_name,email\n12345678,Original,Name,student@example.invalid\n"
        plan = build_import_plan(
            self.user, SimpleUploadedFile("synthetic.csv", raw), course=self.course
        )
        self.assertFalse(plan.is_valid)
        plan = build_import_plan(self.user, SimpleUploadedFile("synthetic.csv", raw))
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.user, self.course, plan)
        self.enrollment.refresh_from_db()
        self.assertIsNotNone(self.enrollment.withdrawn_at)

    def test_referenced_orm_deletion_is_protected(self):
        script = self.verified()
        for record in (
            self.user,
            self.student,
            self.course,
            self.assessment,
            self.enrollment,
            script,
        ):
            with (
                self.subTest(model=type(record).__name__),
                self.assertRaises(ProtectedError),
                transaction.atomic(),
            ):
                record.delete()
        self.assertTrue(script.audit_entries.exists())

    def test_qr_late_pages_freeze_verified_original_revision(self):
        self.assessment.expected_qr_page_labels = ["P1", "P3"]
        self.assessment.qr_test = "KT2"
        self.assessment.save()
        script = create_submission(
            dict(
                assessment=self.assessment,
                file=paper([qr("P1"), qr("P3")]),
                recognition_method="bubble",
            ),
            self.user,
        )
        verify_submission(script, self.enrollment, self.user)
        version = script.version
        name = script.file.name
        script = create_submission(
            dict(
                assessment=self.assessment,
                file=paper([qr("P3")]),
                recognition_method="bubble",
            ),
            self.user,
        )
        revision = script.file_revisions.get(file=name, status="verified")
        self.assertEqual(revision.version, version)
        self.assertEqual(revision.student_identity["student_number"], "12345678")

    def test_excluding_all_qr_pages_clears_current_file_and_retains_evidence(self):
        from submissions.qr import review_page

        self.assessment.expected_qr_page_labels = ["P1"]
        self.assessment.save()
        script = create_submission(
            dict(
                assessment=self.assessment,
                file=paper([qr("P1")]),
                recognition_method="bubble",
            ),
            self.user,
        )
        original = script.file.name
        page = script.pages.first()
        script = review_page(
            script.pk,
            page.pk,
            dict(
                version=script.version, reason="Incorrect physical page", exclude=True
            ),
            self.user,
        )
        self.assertFalse(script.file)
        self.assertTrue(script.file_revisions.filter(file=original).exists())
        self.assertTrue(page.file.storage.exists(page.file.name))
        self.assertEqual(
            self.client.get(f"/api/submissions/{script.pk}/file/").status_code, 404
        )


class RetentionConcurrencyTests(
    RetentionFixtures, TemporaryMediaMixin, TransactionTestCase
):
    def test_parallel_verification_selects_latest_upload_without_unique_race(self):
        old = self.upload()
        new = self.upload()
        barrier = Barrier(2)

        def verify(pk):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    verify_submission(
                        Submission.objects.get(pk=pk), self.enrollment, self.user
                    )
                except ValidationError:
                    pass
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(verify, [old.pk, new.pk]))
        self.assertEqual(
            list(
                Submission.objects.active()
                .filter(status="verified")
                .values_list("pk", flat=True)
            ),
            [new.pk],
        )

    def test_global_archive_aborts_if_membership_scope_grows_while_waiting(self):
        from threading import Event

        from rest_framework.exceptions import APIException

        from students.models import StudentQuerySet

        existing = self.verified()
        second_course = Course.objects.create(
            owner=self.user, code="SECOND", name="Second", year=2023, semester=1
        )
        second_assessment = Assessment.objects.create(
            course=second_course, name="Second test"
        )
        waiting = Event()
        original_get = StudentQuerySet.get

        def get(queryset, *args, **kwargs):
            from threading import current_thread

            if (
                current_thread().name.startswith("archive")
                and queryset.query.select_for_update
            ):
                waiting.set()
            return original_get(queryset, *args, **kwargs)

        def archive():
            close_old_connections()
            try:
                try:
                    archive_student(self.student.pk, self.user, 0, "Global archive")
                except APIException as exc:
                    return exc.status_code
                return 200
            finally:
                close_old_connections()

        with (
            patch.object(StudentQuerySet, "get", get),
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="archive") as executor,
        ):
            with transaction.atomic():
                Student.objects.select_for_update().get(pk=self.student.pk)
                future = executor.submit(archive)
                self.assertTrue(waiting.wait(timeout=10))
                new_enrollment = Enrollment.objects.create(
                    course=second_course, student=self.student
                )
                new_script = create_submission(
                    dict(
                        assessment=second_assessment,
                        file=SimpleUploadedFile("synthetic.pdf", make_pdf()),
                    ),
                    self.user,
                )
                verify_submission(new_script, new_enrollment, self.user)
                queued = schedule_script_email(new_script)
            self.assertEqual(future.result(timeout=10), 409)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.archived_at)
        self.assertFalse(self.student.enrollments.exclude(withdrawn_at=None).exists())
        archive_student(self.student.pk, self.user, 0, "Retry after scope reload")
        queued.refresh_from_db()
        self.assertEqual(queued.status, "superseded")
        self.assertFalse(
            Submission.objects.active()
            .filter(pk__in=[existing.pk, new_script.pk])
            .exists()
        )


class RetentionMigrationTests(TemporaryMediaMixin, TransactionTestCase):
    def test_legacy_duplicates_and_originals_are_retained_with_frozen_identity(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        final = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [
            node
            for node in final
            if node[0] not in {"submissions", "students", "courses", "assessments"}
        ] + [
            (
                "submissions",
                "0015_scriptpage_scriptupload_submission_qr_group_key_and_more",
            ),
            ("students", "0003_enrollment"),
            ("courses", "0003_course_archived_at"),
            ("assessments", "0006_assessment_expected_qr_page_labels_and_more"),
        ]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(final))
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("accounts", "User").objects.create(
            email="legacy@example.invalid"
        )
        course = apps.get_model("courses", "Course").objects.create(
            owner_id=user.pk, code="LEG", name="Legacy", year=2023, semester=1
        )
        assessment = apps.get_model("assessments", "Assessment").objects.create(
            course_id=course.pk, name="Legacy"
        )
        student = apps.get_model("students", "Student").objects.create(
            owner_id=user.pk,
            student_number="99999999",
            first_name="Current",
            last_name="Contact",
            email="legacy.student@example.invalid",
        )
        enrollment = apps.get_model("students", "Enrollment").objects.create(
            course_id=course.pk, student_id=student.pk
        )
        model = apps.get_model("submissions", "Submission")
        older = model.objects.create(
            assessment_id=assessment.pk,
            enrollment_id=enrollment.pk,
            status="verified",
            file="retained/older.pdf",
            original_filename="older.pdf",
            version=4,
        )
        newer = model.objects.create(
            assessment_id=assessment.pk,
            enrollment_id=enrollment.pk,
            status="verified",
            file="retained/newer.pdf",
            original_filename="newer.pdf",
            version=7,
        )
        apps.get_model("submissions", "SubmissionAudit").objects.create(
            submission_id=older.pk,
            new_status="verified",
            new_enrollment_id=enrollment.pk,
            new_identity={"student_number": "12345678", "origin": "transition"},
            reason="Legacy verified",
        )
        email = apps.get_model("distribution", "ScriptEmail").objects.create(
            submission_id=older.pk,
            enrollment_id=enrollment.pk,
            submission_version=4,
            idempotency_key="legacy",
            recipient="legacy.student@example.invalid",
            subject="Legacy",
            body="Legacy",
            attachment_filename="older.pdf",
            status="queued",
        )
        MigrationExecutor(connection).migrate(final)
        from distribution.models import ScriptEmail
        from submissions.models import SubmissionFileRevision

        older_current = Submission.objects.get(pk=older.pk)
        self.assertEqual(older_current.superseded_by_id, newer.pk)
        self.assertEqual(
            Submission.objects.filter(status="verified", superseded_at=None).count(), 1
        )
        self.assertEqual(Submission.objects.count(), 2)
        self.assertEqual(ScriptEmail.objects.get(pk=email.pk).status, "superseded")
        revision = SubmissionFileRevision.objects.get(submission_id=older.pk)
        self.assertEqual(revision.file.name, "retained/older.pdf")
        self.assertEqual(revision.version, 4)
        self.assertEqual(revision.student_identity["student_number"], "12345678")
        self.assertEqual(
            revision.student_identity["origin"], "migration_verified_audit"
        )
        self.assertTrue(
            older_current.audit_entries.filter(
                reason__contains="Legacy duplicate retained"
            ).exists()
        )
