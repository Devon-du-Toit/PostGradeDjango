from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APIClient

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course

from students.models import Enrollment, Student
from assessments.models import Assessment


class AssessmentModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

    def test_create_assessment(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            date=date(2026, 8, 15),
        )

        self.assertEqual(assessment.course, self.course)
        self.assertEqual(assessment.name, "Test 1")
        self.assertEqual(assessment.date, date(2026, 8, 15))

    def test_assessment_string_representation(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        self.assertIn("Test 1", str(assessment))


class AssessmentAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_assessment(self):
        payload = {
            "name": "Test 1",
            "date": "2026-08-15",
        }

        response = self.client.post(
            f"/api/courses/{self.course.id}/assessments/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        assessment = Assessment.objects.get(name="Test 1")

        self.assertEqual(assessment.course, self.course)

    def test_list_only_returns_assessments_for_course(self):
        other_course = Course.objects.create(
            owner=self.user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        Assessment.objects.create(
            course=self.course,
            name="Physics Test",
        )

        Assessment.objects.create(
            course=other_course,
            name="Math Test",
        )

        response = self.client.get(f"/api/courses/{self.course.id}/assessments/")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["name"],
            "Physics Test",
        )

    def test_user_cannot_access_other_users_course_assessments(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        other_course = Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        response = self.client.get(f"/api/courses/{other_course.id}/assessments/")

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_retrieve_own_assessment(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        response = self.client.get(f"/api/assessments/{assessment.id}/")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["name"],
            "Test 1",
        )

    def test_update_own_assessment(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        response = self.client.patch(
            f"/api/assessments/{assessment.id}/",
            {"name": "Test 1 Revised"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        assessment.refresh_from_db()
        self.assertEqual(
            assessment.name,
            "Test 1 Revised",
        )

    def test_delete_own_assessment_archives_it(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        response = self.client.delete(f"/api/assessments/{assessment.id}/")

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        assessment.refresh_from_db()
        self.assertIsNotNone(assessment.archived_at)

        follow_up = self.client.get(f"/api/assessments/{assessment.id}/")
        self.assertEqual(
            follow_up.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_user_cannot_access_other_users_assessment(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        other_course = Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        assessment = Assessment.objects.create(
            course=other_course,
            name="Math Test",
        )

        response = self.client.get(f"/api/assessments/{assessment.id}/")

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_list_assessments(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(f"/api/courses/{self.course.id}/assessments/")

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_course_cannot_be_changed_when_updating_assessment(self):
        other_course = Course.objects.create(
            owner=self.user,
            code="CHE101",
            name="Chemistry",
            year=2026,
            semester=1,
        )

        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
        )

        response = self.client.patch(
            f"/api/assessments/{assessment.id}/",
            {"course": other_course.id},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        assessment.refresh_from_db()
        self.assertEqual(
            assessment.course,
            self.course,
        )
