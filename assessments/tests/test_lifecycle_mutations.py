from django.http import Http404
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from assessments.serializers import AssessmentSerializer
from courses.models import Course
from courses.serializers import CourseSerializer
from students.models import Enrollment, Student
from students.serializers import EnrollmentSerializer


class ActiveScopeMutationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="scope@example.invalid", password="ExamplePassword!42"
        )
        self.context = {"request": type("Request", (), {"user": self.user})()}
        self.course = Course.objects.create(
            owner=self.user, code="CS101", name="Synthetic", year=2026, semester=1
        )
        self.assessment = Assessment.objects.create(course=self.course, name="Original")
        self.student = Student.objects.create(
            owner=self.user,
            student_number="001",
            first_name="Test",
            last_name="Student",
            email="test@x.com",
        )

    def test_assessment_create_validated_before_course_archive_is_rejected(self):
        serializer = AssessmentSerializer(data={"name": "New"}, context=self.context)
        serializer.is_valid(raise_exception=True)
        self.course.archive()
        with self.assertRaises(Http404):
            serializer.save(course=self.course)
        self.assertEqual(Assessment.objects.count(), 1)

    def test_assessment_edit_cannot_write_after_either_parent_is_archived(self):
        serializer = AssessmentSerializer(
            self.assessment,
            data={"name": "Changed"},
            partial=True,
            context=self.context,
        )
        serializer.is_valid(raise_exception=True)
        self.assessment.archive()
        with self.assertRaises(Http404):
            serializer.save()
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.name, "Original")
        Assessment.objects.filter(pk=self.assessment.pk).update(archived_at=None)
        self.course.archive()
        with self.assertRaises(Http404):
            serializer.save()

    def test_course_edit_cannot_write_after_archive(self):
        serializer = CourseSerializer(
            self.course, data={"name": "Changed"}, partial=True, context=self.context
        )
        serializer.is_valid(raise_exception=True)
        self.course.archive()
        with self.assertRaises(Http404):
            serializer.save()
        self.course.refresh_from_db()
        self.assertEqual(self.course.name, "Synthetic")

    def test_enrollment_validated_before_course_archive_is_rejected(self):
        serializer = EnrollmentSerializer(
            data={"course": self.course.pk, "student": self.student.pk},
            context=self.context,
        )
        serializer.is_valid(raise_exception=True)
        self.course.archive()
        with self.assertRaises(Http404):
            serializer.save()
        self.assertFalse(Enrollment.objects.exists())

    def test_duplicate_enrollment_created_after_validation_is_rejected(self):
        from rest_framework.exceptions import ValidationError

        serializer = EnrollmentSerializer(
            data={"course": self.course.pk, "student": self.student.pk},
            context=self.context,
        )
        serializer.is_valid(raise_exception=True)
        Enrollment.objects.create(course=self.course, student=self.student)
        with self.assertRaises(ValidationError):
            serializer.save()
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_assessment_metadata_editing_rejects_grading_and_withdrawal_requires_version(
        self,
    ):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(
            f"/api/assessments/{self.assessment.pk}/",
            {"name": "New label", "date": "2026-10-06"},
        )
        self.assertEqual(response.status_code, 200)
        for field in ("weight", "max_mark", "mark"):
            self.assertEqual(
                client.patch(
                    f"/api/assessments/{self.assessment.pk}/", {field: 10}
                ).status_code,
                400,
            )
        enrollment = Enrollment.objects.create(course=self.course, student=self.student)
        self.assertEqual(
            client.delete(f"/api/enrollments/{enrollment.pk}/").status_code, 400
        )
        self.assertTrue(Enrollment.objects.filter(pk=enrollment.pk).exists())

        self.assertEqual(
            client.delete(
                f"/api/enrollments/{enrollment.pk}/",
                {
                    "version": enrollment.version,
                    "reason": "Lecturer withdrew class membership",
                },
                format="json",
            ).status_code,
            200,
        )
        enrollment.refresh_from_db()
        self.assertIsNotNone(enrollment.withdrawn_at)
