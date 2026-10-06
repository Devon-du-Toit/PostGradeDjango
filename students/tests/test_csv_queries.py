from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from students.csv_import import apply_import_plan, build_import_plan
from students.models import Enrollment, Student
from students.tests.test_csv_import import HEADER, make_course


class CSVQueryBudgetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="bulk@example.invalid")
        self.course = make_course(self.user)

    def plan(self, count=300, **options):
        content = HEADER + "".join(
            f"{index:08},First,Last,student{index}@example.invalid\n"
            for index in range(count)
        )
        with self.assertNumQueries(1):
            plan = build_import_plan(
                self.user,
                SimpleUploadedFile("synthetic.csv", content.encode()),
                **options,
            )
        self.assertTrue(plan.is_valid)
        return plan

    def test_300_new_students_and_memberships_use_seven_queries(self):
        plan = self.plan()
        with self.assertNumQueries(7):
            apply_import_plan(self.user, self.course, plan)
        self.assertEqual(Student.objects.count(), 300)
        self.assertEqual(Enrollment.objects.count(), 300)
        self.assertEqual(
            Student.objects.get(student_number="00000000").first_name, "First"
        )

    def test_repeat_import_is_constant_and_does_not_duplicate_memberships(self):
        apply_import_plan(self.user, self.course, self.plan())
        plan = self.plan()
        with self.assertNumQueries(5):
            apply_import_plan(self.user, self.course, plan)
        self.assertEqual(Enrollment.objects.count(), 300)

    def test_300_contact_updates_use_six_queries_and_preserve_timestamps(self):
        apply_import_plan(self.user, self.course, self.plan())
        original = Student.objects.get(student_number="00000000")
        Student.objects.filter(owner=self.user).update(first_name="Before")
        plan = self.plan(update_existing=True)
        with self.assertNumQueries(6):
            apply_import_plan(self.user, self.course, plan)
        original.refresh_from_db()
        self.assertEqual(original.first_name, "First")
        self.assertGreater(original.updated_at, original.created_at)
        self.assertEqual(Enrollment.objects.count(), 300)

    def test_multiple_batches_import_the_complete_class(self):
        plan = self.plan(1001)
        apply_import_plan(self.user, self.course, plan)
        self.assertEqual(Student.objects.count(), 1001)
        self.assertEqual(Enrollment.objects.count(), 1001)
