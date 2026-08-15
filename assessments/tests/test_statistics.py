from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student


class AssessmentStatisticsViewTests(APITestCase):

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

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        marks = [
            Decimal("40.00"),
            Decimal("25.00"),
            Decimal("45.00"),
        ]

        for index, mark in enumerate(marks):
            student = Student.objects.create(
                owner=self.user,
                student_number=f"1000000{index}",
                first_name="Student",
                last_name=str(index),
                email=f"student{index}@example.com",
            )

            enrollment = Enrollment.objects.create(
                course=self.course,
                student=student,
            )

            Result.objects.create(
                assessment=self.assessment,
                enrollment=enrollment,
                mark=mark,
            )

        self.url = reverse(
            "assessment-statistics",
            kwargs={"pk": self.assessment.id},
        )

    def test_owner_can_retrieve_assessment_statistics(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["assessment"],
            self.assessment.id,
        )
        self.assertEqual(response.data["name"], "Test 1")
        self.assertEqual(response.data["graded_count"], 3)
        self.assertEqual(
            response.data["average_percentage"],
            Decimal("73.33"),
        )
        self.assertEqual(
            response.data["minimum_percentage"],
            Decimal("50.00"),
        )
        self.assertEqual(
            response.data["maximum_percentage"],
            Decimal("90.00"),
        )

    def test_user_cannot_retrieve_another_users_assessment_statistics(self):
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

    def test_unauthenticated_user_cannot_retrieve_assessment_statistics(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )