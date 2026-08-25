import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import IntegrityError
from students.models import Student
from courses.models import Course
from students.models import Enrollment
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile


class StudentModelTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

    def test_create_student(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        self.assertEqual(student.owner, self.user)
        self.assertEqual(student.student_number, "12345678")
        self.assertEqual(student.first_name, "Jane")
        self.assertEqual(student.last_name, "Smith")
        self.assertEqual(student.email, "jane.smith@example.com")

    def test_student_number_unique_per_owner(self):
        Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        with self.assertRaises(IntegrityError):
            Student.objects.create(
                owner=self.user,
                student_number="12345678",
                first_name="John",
                last_name="Doe",
                email="john.doe@example.com",
            )

    def test_enroll_student_in_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        enrollment = Enrollment.objects.create(
            course=course,
            student=student,
        )

        self.assertEqual(enrollment.course, course)
        self.assertEqual(enrollment.student, student)

    def test_student_cannot_be_enrolled_twice_in_same_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        Enrollment.objects.create(
            course=course,
            student=student,
        )

        with self.assertRaises(IntegrityError):
            Enrollment.objects.create(
                course=course,
                student=student,
            )

    def test_cannot_enroll_student_in_another_users_course(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        course = Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        enrollment = Enrollment(
            course=course,
            student=student,
        )

        with self.assertRaises(ValidationError):
            enrollment.full_clean()


class StudentAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_student(self):
        payload = {
            "student_number": "12345678",
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane.smith@example.com",
        }

        response = self.client.post(
            "/api/students/",
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        student = Student.objects.get(
            student_number="12345678"
        )

        self.assertEqual(student.owner, self.user)

    def test_list_only_returns_own_students(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        Student.objects.create(
            owner=other_user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )

        response = self.client.get("/api/students/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["student_number"],
            "12345678",
        )

    def test_unauthenticated_user_cannot_list_students(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/students/")

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_user_cannot_access_other_users_student(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        student = Student.objects.create(
            owner=other_user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )

        response = self.client.get(
            f"/api/students/{student.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_enroll_student_in_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        response = self.client.post(
            "/api/enrollments/",
            {
                "course": course.id,
                "student": student.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertTrue(
            Enrollment.objects.filter(
                course=course,
                student=student,
            ).exists()
        )

    def test_cannot_enroll_other_users_student(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=other_user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )

        response = self.client.post(
            "/api/enrollments/",
            {
                "course": course.id,
                "student": student.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_cannot_enroll_student_in_other_users_course(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        course = Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        response = self.client.post(
            "/api/enrollments/",
            {
                "course": course.id,
                "student": student.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_cannot_create_duplicate_enrollment(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        Enrollment.objects.create(
            course=course,
            student=student,
        )

        response = self.client.post(
            "/api/enrollments/",
            {
                "course": course.id,
                "student": student.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_list_students_for_course(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student_1 = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        student_2 = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )

        Enrollment.objects.create(
            course=course,
            student=student_1,
        )

        Enrollment.objects.create(
            course=course,
            student=student_2,
        )

        response = self.client.get(
            f"/api/courses/{course.id}/students/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(len(response.data), 2)

        student_numbers = {
            student["student_number"]
            for student in response.data
        }

        self.assertEqual(
            student_numbers,
            {"12345678", "87654321"},
        )

    def test_cannot_list_students_for_other_users_course(self):
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        course = Course.objects.create(
            owner=other_user,
            code="MAT101",
            name="Mathematics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=other_user,
            student_number="87654321",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )

        Enrollment.objects.create(
            course=course,
            student=student,
        )

        response = self.client.get(
            f"/api/courses/{course.id}/students/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 0)

    def test_import_students_from_csv(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        csv_content = (
            "student_number,first_name,last_name,email\n"
            "12345678,Jane,Smith,jane.smith@example.com\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        student = Student.objects.get(
            student_number="12345678",
            owner=self.user,
        )

        self.assertTrue(
            Enrollment.objects.filter(
                course=course,
                student=student,
            ).exists()
        )

    def test_import_students_requires_file(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_import_students_rejects_missing_columns(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        csv_content = (
            "student_number,name\n"
            "12345678,Jane Smith\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_import_students_rejects_invalid_email(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        csv_content = (
            "student_number,first_name,last_name,email\n"
            "12345678,Jane,Smith,not-an-email\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Student.objects.filter(
                owner=self.user,
                student_number="12345678",
            ).exists()
        )

    def test_failed_csv_import_rolls_back_created_students(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        csv_content = (
            "student_number,first_name,last_name,email\n"
            "12345678,Jane,Smith,jane.smith@example.com\n"
            "87654321,John,Doe,not-an-email\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Student.objects.filter(
                owner=self.user,
                student_number="12345678",
            ).exists()
        )

        self.assertFalse(
            Enrollment.objects.filter(
                course=course,
            ).exists()
        )

    def test_csv_import_reuses_existing_student(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        existing_student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        csv_content = (
            "student_number,first_name,last_name,email\n"
            "12345678,Jane,Smith,jane.smith@example.com\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            Student.objects.filter(
                owner=self.user,
                student_number="12345678",
            ).count(),
            1,
        )

        self.assertTrue(
            Enrollment.objects.filter(
                course=course,
                student=existing_student,
            ).exists()
        )

    def test_csv_import_does_not_duplicate_existing_enrollment(self):
        course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Introduction to Physics",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
        )

        Enrollment.objects.create(
            course=course,
            student=student,
        )

        csv_content = (
            "student_number,first_name,last_name,email\n"
            "12345678,Jane,Smith,jane.smith@example.com\n"
        )

        csv_file = SimpleUploadedFile(
            "students.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/courses/{course.id}/import-students/",
            {"file": csv_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            Enrollment.objects.filter(
                course=course,
                student=student,
            ).count(),
            1,
        )