from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.tests.helpers import TemporaryMediaMixin


class DeletionGuardTests(TemporaryMediaMixin, TestCase):
    """Courses and assessments that hold recorded data cannot be deleted."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="teacher@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
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

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_result(self, assessment=None):
        return Result.objects.create(
            assessment=assessment or self.assessment,
            enrollment=self.enrollment,
            mark=Decimal("40.00"),
        )

    def make_submission(self, assessment=None):
        return Submission.objects.create(
            assessment=assessment or self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

    def assessment_url(self, assessment=None):
        return reverse(
            "assessment-detail",
            kwargs={"pk": (assessment or self.assessment).pk},
        )

    def course_url(self, course=None):
        return reverse(
            "course-detail",
            kwargs={"pk": (course or self.course).pk},
        )

    # --- Assessments ---

    def test_delete_assessment_with_results_is_blocked(self):
        self.make_result()

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["results"], 1)
        self.assertEqual(response.data["submissions"], 0)
        self.assertTrue(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )
        self.assertEqual(Result.objects.count(), 1)

    def test_delete_assessment_with_only_submissions_is_blocked(self):
        self.make_submission()

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["results"], 0)
        self.assertEqual(response.data["submissions"], 1)
        self.assertTrue(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )
        self.assertEqual(Submission.objects.count(), 1)

    def test_delete_empty_assessment_succeeds(self):
        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )

    def test_other_teacher_cannot_delete_assessment(self):
        self.make_result()
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )

    # --- Courses ---

    def test_delete_course_with_results_is_blocked(self):
        self.make_result()

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["results"], 1)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        self.assertEqual(Result.objects.count(), 1)

    def test_delete_course_with_only_submissions_is_blocked(self):
        self.make_submission()

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["submissions"], 1)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        self.assertEqual(Submission.objects.count(), 1)

    def test_course_counts_cover_all_its_assessments(self):
        second = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )
        self.make_result()
        self.make_result(assessment=second)
        self.make_submission(assessment=second)

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["results"], 2)
        self.assertEqual(response.data["submissions"], 1)

    def test_delete_course_with_no_recorded_data_succeeds(self):
        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Course.objects.filter(pk=self.course.pk).exists())

    def test_other_teacher_cannot_delete_course(self):
        self.make_result()
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())