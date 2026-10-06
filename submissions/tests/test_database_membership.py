"""Exercise actual PostgreSQL constraints rather than model validation."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event

import psycopg
from django.conf import settings
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission


class DatabaseMembershipTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.invalid")
        self.other = User.objects.create_user(email="other@example.invalid")
        self.course = Course.objects.create(
            owner=self.owner, code="ONE", name="One", year=2026, semester=1
        )
        self.second = Course.objects.create(
            owner=self.owner, code="TWO", name="Two", year=2026, semester=1
        )
        self.foreign = Course.objects.create(
            owner=self.other, code="FOREIGN", name="Foreign", year=2026, semester=1
        )
        self.student = Student.objects.create(
            owner=self.owner,
            student_number="12345678",
            first_name="Synthetic",
            last_name="Student",
            email="synthetic@example.invalid",
        )
        self.foreign_student = Student.objects.create(
            owner=self.other,
            student_number="87654321",
            first_name="Other",
            last_name="Student",
            email="other-student@example.invalid",
        )
        self.same_owner_student = Student.objects.create(
            owner=self.owner,
            student_number="11223344",
            first_name="Same",
            last_name="Owner",
            email="same@example.invalid",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course, student=self.student
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Synthetic"
        )
        self.second_assessment = Assessment.objects.create(
            course=self.second, name="Second"
        )
        self.submission = Submission.objects.create(
            assessment=self.assessment, enrollment=self.enrollment, file="synthetic.pdf"
        )

    def test_invalid_bulk_enrollment_and_submission_are_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.bulk_create(
                [Enrollment(course=self.foreign, student=self.student)]
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submission.objects.bulk_create(
                [
                    Submission(
                        assessment=self.second_assessment,
                        enrollment=self.enrollment,
                        file="synthetic.pdf",
                    )
                ]
            )

    def test_queryset_parent_and_child_reassignments_are_rejected(self):
        changes = (
            (Course.objects.filter(pk=self.course.pk), {"owner": self.other}),
            (Student.objects.filter(pk=self.student.pk), {"owner": self.other}),
            (Assessment.objects.filter(pk=self.assessment.pk), {"course": self.second}),
            (Enrollment.objects.filter(pk=self.enrollment.pk), {"course": self.second}),
            (
                Enrollment.objects.filter(pk=self.enrollment.pk),
                {"student": self.foreign_student},
            ),
            (
                Enrollment.objects.filter(pk=self.enrollment.pk),
                {"student": self.same_owner_student},
            ),
            (
                Submission.objects.filter(pk=self.submission.pk),
                {"assessment": self.second_assessment},
            ),
        )
        for queryset, values in changes:
            with self.subTest(model=queryset.model.__name__, values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    queryset.update(**values)

    def test_raw_sql_cannot_spoof_redundant_keys(self):
        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE students_enrollment SET student_id=%s, db_owner_key=%s WHERE id=%s",
                [self.foreign_student.pk, self.other.pk, self.enrollment.pk],
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE submissions_submission SET db_course_key=%s, db_student_key=%s WHERE id=%s RETURNING db_course_key, db_student_key",
                [self.second.pk, self.foreign_student.pk, self.submission.pk],
            )
            self.assertEqual(cursor.fetchone(), (self.course.pk, self.student.pk))

    def test_nullable_enrollment_and_deletion_are_preserved(self):
        self.enrollment.delete()
        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.enrollment_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT db_student_key FROM submissions_submission WHERE id=%s",
                [self.submission.pk],
            )
            self.assertIsNone(cursor.fetchone()[0])
        self.owner.delete()
        self.assertFalse(Submission.objects.filter(pk=self.submission.pk).exists())

    def sql_connection(self):
        database = settings.DATABASES["default"]
        conn = psycopg.connect(
            dbname=connection.settings_dict["NAME"],
            user=database["USER"],
            password=database["PASSWORD"],
            host=database["HOST"],
            port=database["PORT"],
        )
        conn.execute("SET statement_timeout = '5s'")
        conn.execute("SET lock_timeout = '4s'")
        conn.commit()
        return conn

    def test_concurrent_parent_change_cannot_race_child_insert(self):
        # Both transactions initially see a valid owner. FK locking must make
        # the losing transaction fail after the first commits, not admit drift.
        self.submission.delete()
        self.enrollment.delete()
        started = Event()

        def insert_child():
            with self.sql_connection() as conn:
                started.set()
                try:
                    conn.execute(
                        "INSERT INTO students_enrollment (course_id, student_id, created_at) VALUES (%s,%s,NOW())",
                        [self.course.pk, self.student.pk],
                    )
                    conn.commit()
                    return "committed"
                except psycopg.errors.ForeignKeyViolation:
                    conn.rollback()
                    return "rejected"

        with self.sql_connection() as parent, ThreadPoolExecutor(max_workers=1) as pool:
            parent.execute(
                "UPDATE courses_course SET owner_id=%s WHERE id=%s",
                [self.other.pk, self.course.pk],
            )
            future = pool.submit(insert_child)
            self.assertTrue(started.wait(2))
            parent.commit()
            self.assertEqual(future.result(timeout=6), "rejected")
        self.assertFalse(Enrollment.objects.filter(course=self.course).exists())

    def test_child_fk_lock_serializes_parent_reassignment(self):
        self.submission.delete()
        self.enrollment.delete()
        started = Event()

        def change_parent():
            with self.sql_connection() as conn:
                started.set()
                try:
                    conn.execute(
                        "UPDATE courses_course SET owner_id=%s WHERE id=%s",
                        [self.other.pk, self.course.pk],
                    )
                    conn.commit()
                    return "committed"
                except psycopg.errors.ForeignKeyViolation:
                    conn.rollback()
                    return "rejected"

        with self.sql_connection() as child, ThreadPoolExecutor(max_workers=1) as pool:
            child.execute(
                "INSERT INTO students_enrollment (course_id, student_id, created_at) VALUES (%s,%s,NOW())",
                [self.course.pk, self.student.pk],
            )
            future = pool.submit(change_parent)
            self.assertTrue(started.wait(2))
            child.commit()
            self.assertEqual(future.result(timeout=6), "rejected")
        self.course.refresh_from_db()
        self.assertEqual(self.course.owner_id, self.owner.pk)

    def test_concurrent_assessment_or_enrollment_move_cannot_race_submission(self):
        self.submission.delete()
        insert = """INSERT INTO submissions_submission
            (assessment_id,enrollment_id,file,original_filename,status,
             recognition_method,version,created_at,updated_at)
            VALUES (%s,%s,'synthetic.pdf','synthetic.pdf','uploaded','ocr',0,NOW(),NOW())"""
        for table, row_id in (
            ("assessments_assessment", self.assessment.pk),
            ("students_enrollment", self.enrollment.pk),
        ):
            with self.subTest(table=table):
                started = Event()

                def insert_child():
                    with self.sql_connection() as conn:
                        started.set()
                        try:
                            conn.execute(
                                insert, [self.assessment.pk, self.enrollment.pk]
                            )
                            conn.commit()
                            return "committed"
                        except psycopg.errors.ForeignKeyViolation:
                            conn.rollback()
                            return "rejected"

                with (
                    self.sql_connection() as parent,
                    ThreadPoolExecutor(max_workers=1) as pool,
                ):
                    # Table comes only from the fixed cases above, never user input.
                    parent.execute(
                        f"UPDATE {table} SET course_id=%s WHERE id=%s",
                        [self.second.pk, row_id],
                    )
                    future = pool.submit(insert_child)
                    self.assertTrue(started.wait(2))
                    parent.commit()
                    self.assertEqual(future.result(timeout=6), "rejected")
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {table} SET course_id=%s WHERE id=%s",
                        [self.course.pk, row_id],
                    )

    def test_migration_reverses_and_rejects_existing_invalid_data(self):
        migration = import_module(
            "submissions.migrations.0015_database_membership_constraints"
        )
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(migration.REVERSE)
            cursor.execute(
                "UPDATE students_student SET owner_id=%s WHERE id=%s",
                [self.other.pk, self.student.pk],
            )
            with (
                self.assertRaisesRegex(DatabaseError, "Invalid membership data"),
                transaction.atomic(),
            ):
                cursor.execute(migration.FORWARD)
            # No repair happened. Restore the explicit synthetic mismatch and
            # prove forward migration works after operator-approved repair.
            self.student.refresh_from_db()
            self.assertEqual(self.student.owner_id, self.other.pk)
            cursor.execute(
                "UPDATE students_student SET owner_id=%s WHERE id=%s",
                [self.owner.pk, self.student.pk],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(migration.FORWARD)
            transaction.set_rollback(True)

    def test_concurrent_student_owner_change_cannot_race_enrollment(self):
        self.submission.delete()
        self.enrollment.delete()
        started = Event()

        def insert_child():
            with self.sql_connection() as conn:
                started.set()
                try:
                    conn.execute(
                        "INSERT INTO students_enrollment (course_id,student_id,created_at) VALUES (%s,%s,NOW())",
                        [self.course.pk, self.student.pk],
                    )
                    conn.commit()
                    return "committed"
                except psycopg.errors.ForeignKeyViolation:
                    conn.rollback()
                    return "rejected"

        with self.sql_connection() as parent, ThreadPoolExecutor(max_workers=1) as pool:
            parent.execute(
                "UPDATE students_student SET owner_id=%s WHERE id=%s",
                [self.other.pk, self.student.pk],
            )
            future = pool.submit(insert_child)
            self.assertTrue(started.wait(2))
            parent.commit()
            self.assertEqual(future.result(timeout=6), "rejected")

    def test_concurrent_script_insert_fences_same_owner_identity_switch(self):
        self.submission.delete()
        started = Event()

        def switch_identity():
            with self.sql_connection() as conn:
                started.set()
                try:
                    conn.execute(
                        "UPDATE students_enrollment SET student_id=%s WHERE id=%s",
                        [self.same_owner_student.pk, self.enrollment.pk],
                    )
                    conn.commit()
                    return "committed"
                except psycopg.errors.ForeignKeyViolation:
                    conn.rollback()
                    return "rejected"

        with self.sql_connection() as child, ThreadPoolExecutor(max_workers=1) as pool:
            child.execute(
                """INSERT INTO submissions_submission
                (assessment_id,enrollment_id,file,original_filename,status,recognition_method,version,created_at,updated_at)
                VALUES (%s,%s,'synthetic.pdf','synthetic.pdf','uploaded','ocr',0,NOW(),NOW())""",
                [self.assessment.pk, self.enrollment.pk],
            )
            future = pool.submit(switch_identity)
            self.assertTrue(started.wait(2))
            child.commit()
            self.assertEqual(future.result(timeout=6), "rejected")
