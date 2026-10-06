from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from accounts.models import User
from students.csv_import import CSVFileError, apply_import_plan, build_import_plan
from students.models import Enrollment, Student
from students.tests.test_csv_import import HEADER, CSVImportTests, make_course


class CSVHardeningTests(APITestCase):
    upload = CSVImportTests.upload

    def setUp(self):
        CSVImportTests.setUp(self)
        self.context = {"request": type("Request", (), {"user": self.user})()}

    def plan(self, content, **kwargs):
        return build_import_plan(
            self.user,
            SimpleUploadedFile("class.csv", content.encode()),
            serializer_context=self.context,
            **kwargs,
        )

    def student(self):
        return Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )

    def test_headers_trim_whitespace_but_reject_duplicates_and_blank_names(self):
        response = self.upload(
            " student_number , first_name , last_name , email \n001,Ann,Lee,ann@x.com\n"
        )
        self.assertEqual(response.status_code, 200)
        for header in (
            "student_number,first_name,last_name,email,email\n",
            "student_number,first_name,last_name,email,\n",
        ):
            response = self.upload(header + "002,Bob,Ray,bob@x.com,x\n")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Student.objects.count(), 1)

    def test_bad_quoting_and_overlarge_field_return_row_errors_and_no_writes(self):
        for row in (
            '002,"Unclosed,Lee,ann@x.com\n',
            '002,"Ann"junk,Lee,ann@x.com\n',
            "002," + "a" * 140000 + ",Lee,ann@x.com\n",
        ):
            response = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n" + row)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["errors"][0]["row"], 3)
            self.assertFalse(Student.objects.exists())

    def test_physical_row_numbers_include_blank_and_multiline_records(self):
        response = self.upload(HEADER + '\n001,"Ann\nMarie",Lee,ann@x.com\n\n002,Bob\n')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["row"], 6)
        self.assertFalse(Student.objects.exists())

    def test_extra_columns_do_not_hide_a_malformed_blank_row(self):
        response = self.upload(HEADER + ",,,,surplus\n")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["row"], 2)

    def test_bad_import_flags_do_not_accidentally_save_a_preview(self):
        for flags in ({"dry_run": "tru"}, {"update_existing": "perhaps"}):
            response = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n", **flags)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(Student.objects.exists())

    def test_ignored_existing_details_still_require_valid_input(self):
        student = self.student()
        response = self.upload(HEADER + "001,Ann,Lee,invalid-email\n")
        self.assertEqual(response.status_code, 400)
        student.refresh_from_db()
        self.assertEqual(student.email, "ann@x.com")
        self.assertFalse(Enrollment.objects.exists())

    def test_actual_bytes_are_bounded_even_if_reported_size_is_wrong(self):
        stream = BytesIO(b"x" * 100)
        stream.size = 1
        with patch("students.csv_import.MAX_FILE_SIZE_BYTES", 50):
            with self.assertRaises(CSVFileError):
                build_import_plan(self.user, stream, serializer_context=self.context)
        self.assertEqual(stream.tell(), 51)

    def test_stale_plan_returns_conflict_and_does_not_overwrite_student(self):
        student = self.student()
        real = apply_import_plan

        def intervening_write(owner, course, plan):
            Student.objects.filter(pk=student.pk).update(first_name="Manual correction")
            return real(owner, course, plan)

        with patch("students.views.apply_import_plan", side_effect=intervening_write):
            response = self.upload(
                HEADER + "001,Anna,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n",
                update_existing="true",
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["errors"][0]["row"], 2)
        student.refresh_from_db()
        self.assertEqual(student.first_name, "Manual correction")
        self.assertFalse(Student.objects.filter(student_number="002").exists())
        self.assertFalse(Enrollment.objects.exists())

    def test_new_student_appearing_after_preflight_returns_conflict(self):
        plan = self.plan(HEADER + "001,Ann,Lee,ann@x.com\n")
        self.student()
        with self.assertRaises(CSVFileError) as error:
            apply_import_plan(self.user, self.course, plan)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(Enrollment.objects.exists())

    def test_deleted_student_or_invalid_or_foreign_plan_cannot_be_applied(self):
        student = self.student()
        plan = self.plan(HEADER + "001,Ann,Lee,ann@x.com\n")
        student.delete()
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.user, self.course, plan)
        invalid = self.plan(HEADER + "001,Bob\n")
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.user, self.course, invalid)
        with self.assertRaises(CSVFileError):
            apply_import_plan(self.other, self.course, plan)
        self.assertFalse(Student.objects.exists())

    def test_database_conflict_rolls_back_all_creates_updates_and_enrollments(self):
        from django.db import IntegrityError

        student = self.student()
        with patch.object(
            Enrollment.objects,
            "bulk_create",
            side_effect=IntegrityError("synthetic conflict"),
        ):
            response = self.upload(
                HEADER + "001,Anna,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n",
                update_existing="true",
            )
        self.assertEqual(response.status_code, 409)
        student.refresh_from_db()
        self.assertEqual(student.first_name, "Ann")
        self.assertEqual(Student.objects.count(), 1)
        self.assertFalse(Enrollment.objects.exists())

    def test_partial_student_edit_does_not_restore_old_csv_values(self):
        from students.serializers import StudentSerializer

        student = self.student()
        serializer = StudentSerializer(
            student, data={"first_name": "Edited"}, partial=True, context=self.context
        )
        serializer.is_valid(raise_exception=True)
        Student.objects.filter(pk=student.pk).update(email="new@x.com")
        edited = serializer.save()
        self.assertEqual(edited.email, "new@x.com")
        self.assertEqual(edited.first_name, "Edited")


class ConcurrentImportTests(TransactionTestCase):
    def test_competing_plans_cannot_both_create_the_same_student(self):
        user = User.objects.create_user(
            email="import@example.invalid", password="ExamplePassword!42"
        )
        course = make_course(user)
        context = {"request": type("Request", (), {"user": user})()}
        csv = HEADER + "001,Ann,Lee,ann@x.com\n"
        plans = [
            build_import_plan(
                user,
                SimpleUploadedFile("class.csv", csv.encode()),
                serializer_context=context,
            )
            for _ in range(2)
        ]
        barrier = Barrier(2)

        def apply(plan):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                apply_import_plan(user, course, plan)
                return 200
            except CSVFileError as exc:
                return exc.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(apply, plans))
        self.assertCountEqual(statuses, [200, 409])
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)
