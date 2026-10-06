from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MarksRemovalMigrationTests(TransactionTestCase):
    def test_existing_scripts_and_email_history_survive_retirement(self):
        before = [
            ("accounts", "0004_user_role"),
            ("courses", "0003_course_archived_at"),
            ("assessments", "0004_assessment_archived_at"),
            ("distribution", "0001_initial"),
            ("submissions", "0012_bubble_recognition_method_and_evidence"),
        ]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        old = executor.loader.project_state(before).apps
        try:
            user = old.get_model("accounts", "User").objects.create(
                email="migration@example.invalid", password="synthetic"
            )
            course = old.get_model("courses", "Course").objects.create(
                owner_id=user.pk, code="MIG101", name="Migration", year=2026, semester=1
            )
            assessment = old.get_model("assessments", "Assessment").objects.create(
                course_id=course.pk, name="Legacy", max_mark=100, weight=10
            )
            student = old.get_model("students", "Student").objects.create(
                owner_id=user.pk,
                student_number="00123456",
                first_name="Ava",
                last_name="Example",
            )
            enrollment = old.get_model("students", "Enrollment").objects.create(
                course_id=course.pk, student_id=student.pk
            )
            result = old.get_model("assessments", "Result").objects.create(
                assessment_id=assessment.pk, enrollment_id=enrollment.pk, mark=75
            )
            scripts = old.get_model("submissions", "Submission")
            script = scripts.objects.create(
                assessment_id=assessment.pk,
                enrollment_id=enrollment.pk,
                status="marked",
                version=4,
                file="legacy.pdf",
                original_filename="legacy.pdf",
            )
            missing = scripts.objects.create(
                assessment_id=assessment.pk,
                status="marked",
                file="unknown.pdf",
                original_filename="unknown.pdf",
            )
            emails = old.get_model("distribution", "ResultEmail")
            sent = emails.objects.create(
                result_id=result.pk,
                result_version=1,
                idempotency_key="legacy-sent",
                subject="Historical result",
                body="75 / 100",
                status="sent",
            )
            queued = emails.objects.create(
                result_id=result.pk,
                result_version=1,
                idempotency_key="legacy-queued",
                subject="Old queued",
                body="75 / 100",
                status="queued",
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        from assessments.models import Assessment
        from distribution.models import ScriptEmail
        from submissions.models import Submission

        self.assertEqual(Submission.objects.get(pk=script.pk).status, "verified")
        self.assertEqual(Submission.objects.get(pk=script.pk).version, 4)
        self.assertEqual(
            Submission.objects.get(pk=missing.pk).status, "needs_verification"
        )
        self.assertEqual(ScriptEmail.objects.get(pk=sent.pk).status, "sent")
        self.assertEqual(ScriptEmail.objects.get(pk=sent.pk).body, "75 / 100")
        self.assertEqual(ScriptEmail.objects.get(pk=queued.pk).status, "superseded")
        self.assertIsNone(ScriptEmail.objects.get(pk=queued.pk).submission_id)
        self.assertNotIn("assessments_result", connection.introspection.table_names())
        self.assertNotIn("max_mark", [field.name for field in Assessment._meta.fields])
