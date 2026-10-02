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


def listed_ids(response):
    """IDs from a list response, whether or not it is paginated."""
    data = response.data
    items = data["results"] if isinstance(data, dict) else data
    return [item["id"] for item in items]


class ArchiveTests(TemporaryMediaMixin, TestCase):
    """DELETE archives courses and assessments; recorded data is kept."""

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

    def assessment_url(self):
        return reverse("assessment-detail", kwargs={"pk": self.assessment.pk})

    def course_url(self):
        return reverse("course-detail", kwargs={"pk": self.course.pk})

    def assessment_list_url(self):
        return reverse(
            "course-assessment-list-create",
            kwargs={"course_id": self.course.pk},
        )

    def gradebook_url(self):
        return reverse("course-gradebook", kwargs={"course_id": self.course.pk})

    def statistics_url(self):
        return reverse(
            "assessment-statistics",
            kwargs={"pk": self.assessment.pk},
        )

    # --- Assessments ---

    def test_delete_assessment_archives_it_and_keeps_data(self):
        self.make_result()
        self.make_submission()

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assessment.refresh_from_db()
        self.assertIsNotNone(self.assessment.archived_at)
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(Submission.objects.count(), 1)

    def test_archived_assessment_is_hidden(self):
        self.client.delete(self.assessment_url())

        detail = self.client.get(self.assessment_url())
        listing = self.client.get(self.assessment_list_url())
        statistics = self.client.get(self.statistics_url())

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(self.assessment.pk, listed_ids(listing))
        self.assertEqual(statistics.status_code, status.HTTP_404_NOT_FOUND)

    def test_archived_assessment_is_left_out_of_gradebook(self):
        second = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )
        self.make_result()
        self.client.delete(self.assessment_url())

        response = self.client.get(self.gradebook_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [
            item["assessment"]
            for item in response.data["students"][0]["assessments"]
        ]
        self.assertEqual(ids, [second.pk])

    def test_deleting_an_archived_assessment_again_is_404(self):
        self.client.delete(self.assessment_url())

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_teacher_cannot_archive_assessment(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.archived_at)

    # --- Courses ---

    def test_delete_course_archives_it_and_keeps_data(self):
        self.make_result()
        self.make_submission()

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.course.refresh_from_db()
        self.assertIsNotNone(self.course.archived_at)
        self.assertTrue(
            Assessment.objects.filter(pk=self.assessment.pk).exists()
        )
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(Submission.objects.count(), 1)

    def test_archived_course_is_hidden(self):
        self.client.delete(self.course_url())

        detail = self.client.get(self.course_url())
        listing = self.client.get(reverse("course-list-create"))
        assessments = self.client.get(self.assessment_list_url())
        gradebook = self.client.get(self.gradebook_url())

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn(self.course.pk, listed_ids(listing))
        self.assertEqual(assessments.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(gradebook.status_code, status.HTTP_404_NOT_FOUND)

    def test_assessment_of_archived_course_is_hidden(self):
        self.client.delete(self.course_url())

        response = self.client.get(self.assessment_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_teacher_cannot_archive_course(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.delete(self.course_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.course.refresh_from_db()
        self.assertIsNone(self.course.archived_at)

    def test_archived_assessment_is_left_out_of_course_grade(self):
        second = Assessment.objects.create(
            course=self.course,
            name="Test 2",
            max_mark=Decimal("100.00"),
            weight=Decimal("30.00"),
        )
        self.make_result()  # 40 out of 50 = 80%
        Result.objects.create(
            assessment=second,
            enrollment=self.enrollment,
            mark=Decimal("50.00"),  # 50%
        )
        self.client.delete(self.assessment_url())

        response = self.client.get(self.gradebook_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["students"][0]["course_percentage"],
            Decimal("50.00"),
        )