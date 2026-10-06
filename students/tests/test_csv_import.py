from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from courses.models import Course
from students.models import Enrollment, Student
from students.serializers import StudentSerializer

User = get_user_model()

HEADER = "student_number,first_name,last_name,email\n"


def make_course(owner):
    return Course.objects.create(
        owner=owner,
        name="Test Course",
        year=2026,
        semester=1,
    )


def import_url(course):
    return reverse("student-csv-import", kwargs={"course_id": course.id})


class CSVImportTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer1@example.com",
            password="pass12345",
        )
        self.other = User.objects.create_user(
            email="lecturer2@example.com",
            password="pass12345",
        )

        self.course = make_course(self.user)
        self.client.force_authenticate(self.user)

    def upload(self, content, course=None, **extra):
        if isinstance(content, str):
            content = content.encode("utf-8")
        f = SimpleUploadedFile("class.csv", content, content_type="text/csv")
        return self.client.post(
            import_url(course or self.course),
            {"file": f, **extra},
            format="multipart",
        )

    def test_import_passes_request_context_to_serializer(self):
        existing = Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )
        calls = []
        real_validator = StudentSerializer.validate_student_number

        def validate_student_number(serializer, value):
            calls.append((serializer.context["request"].user.pk, serializer.instance))
            return real_validator(serializer, value)

        with patch.object(
            StudentSerializer,
            "validate_student_number",
            validate_student_number,
        ):
            r = self.upload(
                HEADER + "001,Anna,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n",
                update_existing="true",
            )

        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, [(self.user.pk, existing), (self.user.pk, None)])
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Anna")
        self.assertEqual(r.data["summary"]["created"], 1)
        self.assertEqual(r.data["summary"]["updated"], 1)
        self.assertEqual(Enrollment.objects.filter(course=self.course).count(), 2)

    def test_invalid_row_prevents_existing_updates_and_new_students(self):
        existing = Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )
        response = self.upload(
            HEADER
            + "001,Anna,Lee,ann@x.com\n"
            + "002,Bob,Ray,bob@x.com\n"
            + "003,Chris,Ray,invalid-email\n",
            update_existing="true",
        )

        self.assertEqual(response.status_code, 400)
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Ann")
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(response.data["summary"]["total"], 3)
        self.assertEqual(response.data["summary"]["failed"], 1)
        error = response.data["errors"][0]
        self.assertEqual(error["row"], 4)
        self.assertEqual(error["student_number"], "003")
        self.assertIn("email", error["message"])

    def test_dry_run_does_not_update_existing_or_create_new_students(self):
        existing = Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )
        response = self.upload(
            HEADER + "001,Anna,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n",
            update_existing="true",
            dry_run="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["dry_run"])
        self.assertEqual(response.data["summary"]["created"], 1)
        self.assertEqual(response.data["summary"]["updated"], 1)
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Ann")
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 0)

    # ---- criterion 1: parsing ----

    def test_valid_import_creates_students_and_enrollments(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.filter(owner=self.user).count(), 2)
        self.assertEqual(Enrollment.objects.filter(course=self.course).count(), 2)

    def test_utf8_bom_is_handled(self):
        data = b"\xef\xbb\xbf" + (HEADER + "001,Ann,Lee,ann@x.com\n").encode()
        r = self.upload(data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.count(), 1)

    def test_invalid_encoding_returns_400(self):
        r = self.upload(b"\xff\xfe\x00\x00 not utf8 \x80\x81")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Student.objects.count(), 0)

    def test_missing_columns_returns_400(self):
        r = self.upload("student_number,first_name\n001,Ann\n")
        self.assertEqual(r.status_code, 400)

    def test_blank_rows_are_skipped(self):
        r = self.upload(
            HEADER + "001,Ann,Lee,ann@x.com\n,,,\n\n002,Bob,Ray,bob@x.com\n"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.count(), 2)

    def test_malformed_row_reports_row_number_and_saves_nothing(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n002,Bob\n")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["errors"][0]["row"], 3)
        self.assertEqual(Student.objects.count(), 0)

    def test_extra_fields_row_is_an_error(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com,surplus\n")
        self.assertEqual(r.status_code, 400)

    def test_all_errors_are_reported_not_just_the_first(self):
        r = self.upload(HEADER + ",Ann,Lee,ann@x.com\n002,,Ray,bob@x.com\n")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(r.data["errors"]), 2)

    def test_error_response_matches_vue_import_screen(self):
        r = self.upload(HEADER + ",Ann,Lee,ann@x.com\n002,,Ray,bob@x.com\n")
        self.assertEqual(r.status_code, 400)
        first, second = r.data["errors"]
        self.assertEqual(first["student_number"], "")
        self.assertEqual(first["message"], "student_number: This field is required.")
        self.assertEqual(second["student_number"], "002")
        self.assertEqual(second["message"], "first_name: This field is required.")
        self.assertEqual(r.data["summary"]["total"], 2)
        self.assertEqual(r.data["summary"]["failed"], 2)

    def test_success_summary_has_total_and_failed(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n")
        self.assertEqual(r.status_code, 200)
        summary = r.data["summary"]
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["failed"], 0)

    def test_whitespace_is_stripped(self):
        r = self.upload(HEADER + "  001 ,  Ann , Lee ,  ann@x.com \n")
        self.assertEqual(r.status_code, 200)
        s = Student.objects.get()
        self.assertEqual(s.student_number, "001")
        self.assertEqual(s.first_name, "Ann")

    def test_duplicate_numbers_in_file_are_errors(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n001,Bob,Ray,bob@x.com\n")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["errors"][0]["row"], 3)
        self.assertEqual(Student.objects.count(), 0)

    def test_oversized_file_rejected(self):
        with patch("students.csv_import.MAX_FILE_SIZE_BYTES", 50):
            r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n" * 5)
        self.assertEqual(r.status_code, 400)

    def test_row_cap_rejected(self):
        with patch("students.csv_import.MAX_ROWS", 2):
            r = self.upload(
                HEADER + "001,A,A,a@x.com\n002,B,B,b@x.com\n003,C,C,c@x.com\n"
            )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Student.objects.count(), 0)

    # ---- criterion 2: dry run and update policy ----

    def test_dry_run_writes_nothing(self):
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n", dry_run="true")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["dry_run"])
        self.assertEqual(r.data["summary"]["created"], 1)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_existing_student_not_overwritten_but_mismatch_reported(self):
        Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )
        r = self.upload(HEADER + "001,Anna,Lee,ann@x.com\n")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.get().first_name, "Ann")
        self.assertEqual(len(r.data["mismatches"]), 1)
        self.assertIn("first_name", r.data["mismatches"][0]["differences"])
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_update_existing_flag_applies_changes(self):
        Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Ann",
            last_name="Lee",
            email="ann@x.com",
        )
        r = self.upload(HEADER + "001,Anna,Lee,ann@x.com\n", update_existing="true")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.get().first_name, "Anna")
        self.assertEqual(r.data["summary"]["updated"], 1)

    # ---- criterion 3: identity, repeat imports, isolation, atomicity ----

    def test_leading_zeros_preserved(self):
        self.upload(HEADER + "00123,Ann,Lee,ann@x.com\n")
        self.assertEqual(Student.objects.get().student_number, "00123")

    def test_repeat_import_is_idempotent(self):
        csv_text = HEADER + "00123,Ann,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n"
        self.upload(csv_text)
        r = self.upload(csv_text)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Student.objects.count(), 2)
        self.assertEqual(Enrollment.objects.count(), 2)
        self.assertEqual(Student.objects.get(student_number="00123").first_name, "Ann")

    def test_cross_owner_isolation(self):
        theirs = Student.objects.create(
            owner=self.other,
            student_number="001",
            first_name="Zed",
            last_name="Zee",
            email="zed@x.com",
        )
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n", update_existing="true")
        self.assertEqual(r.status_code, 200)
        theirs.refresh_from_db()
        self.assertEqual(theirs.first_name, "Zed")
        mine = Student.objects.get(owner=self.user, student_number="001")
        self.assertNotEqual(mine.pk, theirs.pk)

    def test_cannot_import_into_another_users_course(self):
        theirs = make_course(self.other)
        r = self.upload(HEADER + "001,Ann,Lee,ann@x.com\n", course=theirs)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Student.objects.count(), 0)

    def test_failure_during_apply_rolls_back_everything(self):
        calls = {"n": 0}
        real = Enrollment.objects.get_or_create

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        with patch.object(Enrollment.objects, "get_or_create", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.upload(HEADER + "001,Ann,Lee,ann@x.com\n002,Bob,Ray,bob@x.com\n")
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(Enrollment.objects.count(), 0)
