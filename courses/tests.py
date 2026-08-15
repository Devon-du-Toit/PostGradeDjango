from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import IntegrityError
from courses.models import Course
from rest_framework import status
from rest_framework.test import APIClient


class CourseModelTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

    def test_create_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        self.assertEqual(course.owner, self.user)
        self.assertEqual(course.code, "PHY101")
        self.assertEqual(course.name, "Introduction to Physics")
        self.assertEqual(course.year, 2026)
        self.assertEqual(course.semester, 1)

    def test_course_unique_per_owner_year_and_semester(self):
        Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        with self.assertRaises(IntegrityError):
            Course.objects.create(
                owner=self.user,
                code="PHY101",
                name="Introduction to Physics",
                year=2026,
                semester=1,
            )

    def test_course_string_representation(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        self.assertEqual(str(course), "PHY101 - Introduction to Physics")

    def test_same_course_allowed_for_different_owner(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        course = Course.objects.create(
            owner=other_user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        self.assertEqual(course.owner, other_user)


class CourseAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_course(self):
        payload = {
            "code": "PHY101",
            "name": "Introduction to Physics",
            "year": 2026,
            "semester": 1,
        }

        response = self.client.post(
            "/api/courses/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        course = Course.objects.get(code="PHY101")
        self.assertEqual(course.owner, self.user)

    def test_list_only_returns_own_courses(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        response = self.client.get("/api/courses/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["code"], "PHY101")

    def test_unauthenticated_user_cannot_list_courses(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/courses/")

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_user_cannot_access_other_users_course(self):
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

        response = self.client.get(
            f"/api/courses/{other_course.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_update_own_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        response = self.client.patch(
            f"/api/courses/{course.id}/",
            {"name": "Introductory Physics"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        course.refresh_from_db()
        self.assertEqual(course.name, "Introductory Physics")

    def test_delete_own_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        response = self.client.delete(
            f"/api/courses/{course.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertFalse(
            Course.objects.filter(id=course.id).exists()
        )