from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student


class CourseGradebookViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        self.url = reverse(
            "course-gradebook",
            kwargs={"course_id": self.course.id},
        )

    def test_owner_can_retrieve_course_gradebook(self):
        self.client.force_authenticate(user=self.user)

        Assessment.objects.create(
            course=self.course,
            name="Final Exam",
            max_mark=Decimal("100.00"),
            weight=Decimal("80.00"),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["course"], self.course.id)
        self.assertEqual(len(response.data["students"]), 1)

        student_data = response.data["students"][0]

        self.assertEqual(
            student_data["student_number"],
            "12345678",
        )
        self.assertEqual(
            student_data["course_percentage"],
            Decimal("80.00"),
        )
        self.assertEqual(len(student_data["assessments"]), 2)

        assessment_by_name = {
            item["name"]: item
            for item in student_data["assessments"]
        }

        assessment_data = assessment_by_name["Test 1"]

        self.assertEqual(
            assessment_data["name"],
            "Test 1",
        )
        self.assertEqual(
            assessment_data["mark"],
            Decimal("40.00"),
        )
        self.assertEqual(
            assessment_data["max_mark"],
            Decimal("50.00"),
        )
        self.assertEqual(
            assessment_data["percentage"],
            Decimal("80.00"),
        )
        self.assertEqual(
            assessment_data["weight"],
            Decimal("20.00"),
        )

        final_exam_data = assessment_by_name["Final Exam"]

        self.assertEqual(
            final_exam_data["name"],
            "Final Exam",
        )
        self.assertIsNone(final_exam_data["mark"])
        self.assertIsNone(final_exam_data["percentage"])
        self.assertEqual(
            final_exam_data["max_mark"],
            Decimal("100.00"),
        )
        self.assertEqual(
            final_exam_data["weight"],
            Decimal("80.00"),
        )

    def test_user_cannot_retrieve_another_users_gradebook(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        self.client.force_authenticate(user=other_user)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_retrieve_gradebook(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_gradebook_returns_multiple_students_with_individual_grades(self):
        second_student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        second_enrollment = Enrollment.objects.create(
            course=self.course,
            student=second_student,
        )

        Result.objects.create(
            assessment=self.assessment,
            enrollment=second_enrollment,
            mark=Decimal("25.00"),
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["students"]), 2)

        students_by_number = {
            item["student_number"]: item
            for item in response.data["students"]
        }

        self.assertEqual(
            students_by_number["12345678"]["course_percentage"],
            Decimal("80.00"),
        )

        self.assertEqual(
            students_by_number["87654321"]["course_percentage"],
            Decimal("50.00"),
        )