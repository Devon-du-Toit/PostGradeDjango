"""QR page/source/identity membership stays valid for ordinary SQL writes."""

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from io import StringIO
from threading import Event
from unittest.mock import patch

import psycopg
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase

from assessments.models import Assessment
from students.models import Enrollment
from submissions.models import ScriptPage, ScriptUpload, Submission
from submissions.tests import test_database_membership as membership_tests


class QRDatabaseMembershipTests(TransactionTestCase):
    def setUp(self):
        membership_tests.DatabaseMembershipTests.setUp(self)
        self.other_assessment = Assessment.objects.create(
            course=self.course, name="Other same-course test"
        )
        self.foreign_assessment = Assessment.objects.create(
            course=self.foreign, name="Foreign"
        )
        self.other_submission = Submission.objects.create(
            assessment=self.other_assessment, file="other.pdf"
        )
        self.foreign_submission = Submission.objects.create(
            assessment=self.foreign_assessment, file="foreign.pdf"
        )
        self.upload = ScriptUpload.objects.create(
            assessment=self.assessment,
            file="source.pdf",
            original_filename="source.pdf",
        )
        self.foreign_upload = ScriptUpload.objects.create(
            assessment=self.foreign_assessment,
            file="foreign-source.pdf",
            original_filename="foreign-source.pdf",
        )
        self.foreign_enrollment = Enrollment.objects.create(
            course=self.foreign, student=self.foreign_student
        )
        self.other_enrollment = Enrollment.objects.create(
            course=self.course, student=self.same_owner_student
        )
        self.page = ScriptPage.objects.create(
            submission=self.submission,
            upload=self.upload,
            file="page.pdf",
            source_page=1,
            source_filename="source.pdf",
            qr_status="readable",
            page_label="P1",
            suggested_enrollment=self.enrollment,
            linked_enrollment=self.enrollment,
        )

    def test_bulk_page_insert_rejects_foreign_source_and_membership(self):
        for extra in (
            {"upload": self.foreign_upload},
            {"suggested_enrollment": self.foreign_enrollment},
            {"linked_enrollment": self.foreign_enrollment},
            {"linked_enrollment": self.other_enrollment},
        ):
            with self.subTest(fields=list(extra)):
                values = dict(
                    submission=self.submission,
                    upload=self.upload,
                    file="page.pdf",
                    source_page=2,
                    source_filename="source.pdf",
                    qr_status="readable",
                    page_label="P3",
                )
                values.update(extra)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    ScriptPage.objects.bulk_create([ScriptPage(**values)])

    def test_queryset_page_and_parent_reassignments_are_rejected(self):
        changes = (
            (
                ScriptPage.objects.filter(pk=self.page.pk),
                {"submission": self.other_submission},
            ),
            (
                ScriptPage.objects.filter(pk=self.page.pk),
                {"submission": self.foreign_submission},
            ),
            (
                ScriptPage.objects.filter(pk=self.page.pk),
                {"upload": self.foreign_upload},
            ),
            (
                ScriptPage.objects.filter(pk=self.page.pk),
                {"suggested_enrollment": self.foreign_enrollment},
            ),
            (
                ScriptPage.objects.filter(pk=self.page.pk),
                {"linked_enrollment": self.other_enrollment},
            ),
            (
                Submission.objects.filter(pk=self.submission.pk),
                {"assessment": self.other_assessment},
            ),
            (
                ScriptUpload.objects.filter(pk=self.upload.pk),
                {"assessment": self.other_assessment},
            ),
        )
        for queryset, values in changes:
            with self.subTest(model=queryset.model.__name__, fields=list(values)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    queryset.update(**values)

    def test_raw_sql_cannot_spoof_page_scope_keys(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE submissions_scriptpage SET db_assessment_key=%s, db_course_key=%s WHERE id=%s RETURNING db_assessment_key,db_course_key",
                [self.foreign_assessment.pk, self.foreign.pk, self.page.pk],
            )
            self.assertEqual(cursor.fetchone(), (self.assessment.pk, self.course.pk))
        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE submissions_scriptpage SET submission_id=%s WHERE id=%s",
                [self.foreign_submission.pk, self.page.pk],
            )

    def test_link_clear_and_relink_allow_parent_first_ordering(self):
        with transaction.atomic():
            Submission.objects.filter(pk=self.submission.pk).update(enrollment=None)
            ScriptPage.objects.filter(pk=self.page.pk).update(linked_enrollment=None)
        self.page.refresh_from_db()
        self.assertIsNone(self.page.linked_enrollment_id)
        with transaction.atomic():
            Submission.objects.filter(pk=self.submission.pk).update(
                enrollment=self.other_enrollment
            )
            ScriptPage.objects.filter(pk=self.page.pk).update(
                linked_enrollment=self.other_enrollment
            )
        self.page.refresh_from_db()
        self.assertEqual(self.page.linked_enrollment_id, self.other_enrollment.pk)

    def test_link_correction_allows_page_first_ordering_but_not_bad_commit(self):
        with transaction.atomic():
            ScriptPage.objects.filter(pk=self.page.pk).update(
                linked_enrollment=self.other_enrollment
            )
            Submission.objects.filter(pk=self.submission.pk).update(
                enrollment=self.other_enrollment
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submission.objects.filter(pk=self.submission.pk).update(enrollment=None)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.enrollment_id, self.other_enrollment.pk)

    def test_migration_and_audit_reject_existing_cross_assessment_page(self):
        migration = import_module(
            "submissions.migrations.0017_database_membership_constraints"
        )
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(migration.REVERSE)
            cursor.execute(
                "UPDATE submissions_scriptpage SET upload_id=%s WHERE id=%s",
                [self.foreign_upload.pk, self.page.pk],
            )
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "audit_database_integrity", fail_on_invalid=True, stdout=output
                )
            report = json.loads(output.getvalue())
            self.assertEqual(report["invalid_qr_page_scopes"], 1)
            self.assertEqual(report["invalid_qr_page_links"], 0)
            with (
                self.assertRaisesRegex(DatabaseError, "Invalid membership data"),
                transaction.atomic(),
            ):
                cursor.execute(migration.FORWARD)
            self.page.refresh_from_db()
            self.assertEqual(self.page.upload_id, self.foreign_upload.pk)
            cursor.execute(
                "UPDATE submissions_scriptpage SET upload_id=%s WHERE id=%s",
                [self.upload.pk, self.page.pk],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(migration.FORWARD)
            transaction.set_rollback(True)

    def test_read_only_audit_detects_deferred_page_identity_mismatch(self):
        with transaction.atomic():
            ScriptPage.objects.filter(pk=self.page.pk).update(
                linked_enrollment=self.other_enrollment
            )
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "audit_database_integrity", fail_on_invalid=True, stdout=output
                )
            report = json.loads(output.getvalue())
            self.assertEqual(report["invalid_qr_page_links"], 1)
            self.assertEqual(report["invalid_qr_page_enrollments"], 0)
            transaction.set_rollback(True)

    def test_pre_qr_schema_audit_skips_page_queries_explicitly(self):
        tables = [
            table
            for table in connection.introspection.table_names()
            if table != ScriptPage._meta.db_table
        ]
        output = StringIO()
        with patch.object(connection.introspection, "table_names", return_value=tables):
            call_command(
                "audit_database_integrity", fail_on_invalid=True, stdout=output
            )
        report = json.loads(output.getvalue())
        self.assertFalse(report["qr_schema_available"])
        self.assertIsNone(report["invalid_qr_page_scopes"])

    def test_concurrent_parent_scope_move_cannot_race_page_insert(self):
        self.page.delete()
        insert = """INSERT INTO submissions_scriptpage
            (submission_id,upload_id,file,source_page,source_filename,qr_fields,
             qr_status,page_label,excluded,review_history,recognition_outcome,
             quality_issues,created_at)
            VALUES (%s,%s,'page.pdf',1,'source.pdf','{}','readable','P1',FALSE,'[]','','[]',NOW())"""
        cases = (
            ("submissions_submission", self.submission.pk),
            ("submissions_scriptupload", self.upload.pk),
        )
        for table, row_id in cases:
            with self.subTest(table=table):
                started = Event()

                def insert_page():
                    with membership_tests.DatabaseMembershipTests.sql_connection(
                        self
                    ) as conn:
                        started.set()
                        try:
                            conn.execute(insert, [self.submission.pk, self.upload.pk])
                            conn.commit()
                            return "committed"
                        except psycopg.errors.ForeignKeyViolation:
                            conn.rollback()
                            return "rejected"

                with (
                    membership_tests.DatabaseMembershipTests.sql_connection(
                        self
                    ) as parent,
                    ThreadPoolExecutor(max_workers=1) as pool,
                ):
                    # Names come only from the two fixed cases above.
                    parent.execute(
                        f"UPDATE {table} SET assessment_id=%s WHERE id=%s",
                        [self.other_assessment.pk, row_id],
                    )
                    future = pool.submit(insert_page)
                    self.assertTrue(started.wait(2))
                    parent.commit()
                    self.assertEqual(future.result(timeout=6), "rejected")
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {table} SET assessment_id=%s WHERE id=%s",
                        [self.assessment.pk, row_id],
                    )

