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
from assessments.models import Assessment, Result


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
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
            date=date(2026, 8, 15),
        )

        self.assertEqual(assessment.course, self.course)
        self.assertEqual(assessment.name, "Test 1")
        self.assertEqual(assessment.max_mark, Decimal("50.00"))
        self.assertEqual(assessment.weight, Decimal("20.00"))
        self.assertEqual(assessment.date, date(2026, 8, 15))

    def test_assessment_string_representation(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        self.assertIn("Test 1", str(assessment))

    def test_max_mark_must_be_greater_than_zero(self):
        assessment = Assessment(
            course=self.course,
            name="Invalid Test",
            max_mark=Decimal("0.00"),
            weight=Decimal("20.00"),
        )

        with self.assertRaises(ValidationError):
            assessment.full_clean()

    def test_weight_cannot_be_negative(self):
        assessment = Assessment(
            course=self.course,
            name="Invalid Test",
            max_mark=Decimal("50.00"),
            weight=Decimal("-1.00"),
        )

        with self.assertRaises(ValidationError):
            assessment.full_clean()

    def test_weight_cannot_exceed_100(self):
        assessment = Assessment(
            course=self.course,
            name="Invalid Test",
            max_mark=Decimal("50.00"),
            weight=Decimal("101.00"),
        )

        with self.assertRaises(ValidationError):
            assessment.full_clean()


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
            "max_mark": "50.00",
            "weight": "20.00",
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
        self.assertEqual(
            assessment.max_mark,
            Decimal("50.00"),
        )
        self.assertEqual(
            assessment.weight,
            Decimal("20.00"),
        )

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
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        Assessment.objects.create(
            course=other_course,
            name="Math Test",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )

        response = self.client.get(
            f"/api/courses/{self.course.id}/assessments/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["name"],
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

        response = self.client.get(
            f"/api/courses/{other_course.id}/assessments/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_retrieve_own_assessment(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        response = self.client.get(
            f"/api/assessments/{assessment.id}/"
        )

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
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
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

    def test_delete_own_assessment(self):
        assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
        )

        response = self.client.delete(
            f"/api/assessments/{assessment.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.assertFalse(
            Assessment.objects.filter(
                id=assessment.id
            ).exists()
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
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )

        response = self.client.get(
            f"/api/assessments/{assessment.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_list_assessments(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            f"/api/courses/{self.course.id}/assessments/"
        )

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
            max_mark=Decimal("50.00"),
            weight=Decimal("20.00"),
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


class ResultModelTests(TestCase):

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

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
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

    def test_create_result(self):
        result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("42.00"),
        )

        self.assertEqual(result.assessment, self.assessment)
        self.assertEqual(result.enrollment, self.enrollment)
        self.assertEqual(result.mark, Decimal("42.00"))

    def test_result_string_representation(self):
        result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("42.00"),
        )

        self.assertIn("Test 1", str(result))
        self.assertIn("42.00", str(result))

    def test_duplicate_result_not_allowed(self):
        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("42.00"),
        )

        with self.assertRaises(IntegrityError):
            Result.objects.create(
                assessment=self.assessment,
                enrollment=self.enrollment,
                mark=Decimal("40.00"),
            )

    def test_negative_mark_not_allowed(self):
        result = Result(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("-1.00"),
        )

        with self.assertRaises(ValidationError):
            result.full_clean()

    def test_mark_cannot_exceed_max_mark(self):
        result = Result(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("51.00"),
        )

        with self.assertRaises(ValidationError):
            result.full_clean()

    def test_enrollment_must_belong_to_assessment_course(self):
        other_course = Course.objects.create(
            owner=self.user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        other_enrollment = Enrollment.objects.create(
            course=other_course,
            student=self.student,
        )

        result = Result(
            assessment=self.assessment,
            enrollment=other_enrollment,
            mark=Decimal("40.00"),
        )

        with self.assertRaises(ValidationError):
            result.full_clean()


class ResultAPITests(TestCase):

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

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
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

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_result(self):
        payload = {
            "enrollment": self.enrollment.id,
            "mark": "42.00",
        }

        response = self.client.post(
            f"/api/assessments/{self.assessment.id}/results/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        result = Result.objects.get(
            assessment=self.assessment,
            enrollment=self.enrollment,
        )

        self.assertEqual(result.mark, Decimal("42.00"))

    def test_result_response_contains_percentage(self):
        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/results/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            Decimal(str(response.data[0]["percentage"])),
            Decimal("80.00"),
        )

    def test_list_only_returns_results_for_assessment(self):
        other_assessment = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )

        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        Result.objects.create(
            assessment=other_assessment,
            enrollment=self.enrollment,
            mark=Decimal("75.00"),
        )

        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/results/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["mark"],
            "40.00",
        )

    def test_mark_cannot_exceed_max_mark(self):
        payload = {
            "enrollment": self.enrollment.id,
            "mark": "51.00",
        }

        response = self.client.post(
            f"/api/assessments/{self.assessment.id}/results/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_enrollment_must_belong_to_same_course(self):
        other_course = Course.objects.create(
            owner=self.user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        other_enrollment = Enrollment.objects.create(
            course=other_course,
            student=self.student,
        )

        payload = {
            "enrollment": other_enrollment.id,
            "mark": "40.00",
        }

        response = self.client.post(
            f"/api/assessments/{self.assessment.id}/results/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_update_own_result(self):
        result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        response = self.client.patch(
            f"/api/results/{result.id}/",
            {"mark": "45.00"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        result.refresh_from_db()
        self.assertEqual(result.mark, Decimal("45.00"))

    def test_delete_own_result(self):
        result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        response = self.client.delete(
            f"/api/results/{result.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.assertFalse(
            Result.objects.filter(id=result.id).exists()
        )

    def test_user_cannot_access_other_users_result(self):
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

        other_student = Student.objects.create(
            owner=other_user,
            student_number="87654321",
            first_name="Bob",
            last_name="Jones",
            email="bob@example.com",
        )

        other_enrollment = Enrollment.objects.create(
            course=other_course,
            student=other_student,
        )

        other_assessment = Assessment.objects.create(
            course=other_course,
            name="Math Test",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )

        result = Result.objects.create(
            assessment=other_assessment,
            enrollment=other_enrollment,
            mark=Decimal("80.00"),
        )

        response = self.client.get(
            f"/api/results/{result.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_list_results(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/results/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_duplicate_result_not_allowed_via_api(self):
        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

        payload = {
            "enrollment": self.enrollment.id,
            "mark": "45.00",
        }

        response = self.client.post(
            f"/api/assessments/{self.assessment.id}/results/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            Result.objects.filter(
                assessment=self.assessment,
                enrollment=self.enrollment,
            ).count(),
            1,
        )

    def test_result_response_contains_student_details(self):
        Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("42.00"),
        )

        response = self.client.get(
            f"/api/assessments/{self.assessment.id}/results/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data[0]["student_number"],
            "12345678",
        )

        self.assertEqual(
            response.data[0]["student_name"],
            "Alice Smith",
        )