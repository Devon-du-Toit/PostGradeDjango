from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from distribution.models import ScriptEmail
from students.models import Enrollment, Student
from submissions.models import RecognitionJob, Submission, SubmissionAudit


class EndpointPermissionMatrixTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.invalid", password="ExamplePassword!42"
        )
        self.other = User.objects.create_user(
            email="other@example.invalid", password="ExamplePassword!42"
        )
        self.course = Course.objects.create(
            owner=self.owner, code="CS101", name="Synthetic", year=2026, semester=1
        )
        self.student = Student.objects.create(
            owner=self.owner,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course, student=self.student
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Synthetic"
        )
        self.submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            file="submissions/private.pdf",
            original_filename="private.pdf",
            status="verified",
        )
        self.email = ScriptEmail.objects.create(
            submission=self.submission,
            enrollment=self.enrollment,
            subject="Private",
            body="Private body",
            recipient="student@example.invalid",
            status="awaiting_approval",
            idempotency_key="permission-test",
        )
        c, a, s, u, e = (
            self.course.pk,
            self.assessment.pk,
            self.student.pk,
            self.submission.pk,
            self.email.pk,
        )
        self.routes = [
            ("get", f"courses/{c}/", {}),
            ("patch", f"courses/{c}/", {"name": "changed"}),
            ("put", f"courses/{c}/", {}),
            ("delete", f"courses/{c}/", {}),
            ("get", f"courses/{c}/students/", {}),
            ("post", f"courses/{c}/import-students/", {}),
            ("get", f"courses/{c}/assessments/", {}),
            ("post", f"courses/{c}/assessments/", {"name": "changed"}),
            ("get", f"students/{s}/", {}),
            ("patch", f"students/{s}/", {"first_name": "changed"}),
            ("put", f"students/{s}/", {}),
            ("delete", f"students/{s}/", {}),
            ("post", f"students/{s}/email/", {"subject": "x", "message": "x"}),
            ("get", f"assessments/{a}/", {}),
            ("patch", f"assessments/{a}/", {"name": "changed"}),
            ("put", f"assessments/{a}/", {}),
            ("delete", f"assessments/{a}/", {}),
            ("get", f"submissions/{u}/", {}),
            ("patch", f"submissions/{u}/", {"version": 0}),
            ("put", f"submissions/{u}/", {}),
            ("delete", f"submissions/{u}/", {}),
            ("post", f"submissions/{u}/verify/", {"enrollment": self.enrollment.pk}),
            (
                "post",
                f"submissions/{u}/correct/",
                {"enrollment": self.enrollment.pk, "version": 0, "reason": "test"},
            ),
            ("post", f"submissions/{u}/retry-recognition/", {}),
            ("post", f"submissions/{u}/email/", {}),
            ("get", f"submissions/{u}/file/", {}),
            ("get", f"submissions/{u}/recognition-image/", {}),
            ("get", f"assessments/{a}/script-emails/", {}),
            ("post", f"assessments/{a}/script-emails/approve/", {}),
            ("get", f"script-emails/{e}/", {}),
            ("post", f"script-emails/{e}/approve/", {}),
            ("post", f"script-emails/{e}/retry/", {}),
        ]
        self.client = APIClient()

    def assert_unchanged(self):
        self.course.refresh_from_db()
        self.student.refresh_from_db()
        self.assessment.refresh_from_db()
        self.submission.refresh_from_db()
        self.email.refresh_from_db()
        self.assertEqual(self.course.name, "Synthetic")
        self.assertEqual(self.student.first_name, "Test")
        self.assertEqual(self.assessment.name, "Synthetic")
        self.assertIsNone(self.course.archived_at)
        self.assertIsNone(self.assessment.archived_at)
        self.assertEqual(self.submission.status, "verified")
        self.assertEqual(self.email.status, "awaiting_approval")
        self.assertEqual(ScriptEmail.objects.count(), 1)
        self.assertFalse(RecognitionJob.objects.exists())
        self.assertFalse(SubmissionAudit.objects.exists())

    def test_anonymous_requests_cannot_read_or_mutate_domain_endpoints(self):
        routes = self.routes + [
            ("get", path, {})
            for path in (
                "courses/",
                "students/",
                "enrollments/",
                "students/enrollments/",
                "submissions/",
                "submissions/verification-queue/",
                "submissions/recognition-methods/",
                "dashboard/stats/",
                "dashboard/assessments/",
                "auth/me/",
            )
        ]
        routes += [
            ("post", path, {})
            for path in (
                "courses/",
                "students/",
                "enrollments/",
                "students/enrollments/",
                "submissions/",
            )
        ]
        for method, path, data in routes:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    f"/api/{path}", data, format="json"
                )
                self.assertEqual(response.status_code, 401)
        self.assert_unchanged()

    def test_every_role_including_staff_admin_is_owner_scoped(self):
        with (
            patch("students.views.send_student_email") as send,
            patch("submissions.views.FileResponse") as files,
        ):
            for role in User.Role.values:
                self.other.role = role
                self.other.is_staff = role == User.Role.ADMIN
                self.other.is_superuser = role == User.Role.ADMIN
                self.other.save()
                self.client.force_authenticate(self.other)
                for method, path, data in self.routes:
                    with self.subTest(role=role, method=method, path=path):
                        response = getattr(self.client, method)(
                            f"/api/{path}", data, format="json"
                        )
                        self.assertEqual(response.status_code, 404)
                self.assert_unchanged()
            send.assert_not_called()
            files.assert_not_called()

    def test_foreign_keys_and_filtered_lists_cannot_bypass_ownership(self):
        self.client.force_authenticate(self.other)
        for path in ("enrollments/", "students/enrollments/"):
            response = self.client.post(
                f"/api/{path}", {"course": self.course.pk, "student": self.student.pk}
            )
            self.assertEqual(response.status_code, 400)
        for path in (
            "courses/",
            "students/",
            "enrollments/",
            "students/enrollments/",
            "submissions/",
            "submissions/verification-queue/",
            "dashboard/assessments/",
        ):
            response = self.client.get(
                f"/api/{path}",
                {"course": self.course.pk, "assessment": self.assessment.pk},
            )
            self.assertIn(response.status_code, (200, 400))
            if response.status_code == 200:
                self.assertEqual(response.data["results"], [])
            unfiltered = self.client.get(f"/api/{path}")
            self.assertEqual(unfiltered.status_code, 200)
            self.assertEqual(unfiltered.data["results"], [])
        stats = self.client.get("/api/dashboard/stats/")
        self.assertEqual(stats.data["active_courses"], 0)
        self.assertEqual(stats.data["pending_verifications"], 0)
        self.assert_unchanged()

    def test_role_label_does_not_grant_django_admin_access(self):
        from django.test import Client

        self.other.role = User.Role.ADMIN
        self.other.save()
        browser = Client()
        browser.force_login(self.other)
        self.assertEqual(browser.get("/admin/").status_code, 302)
        self.assertEqual(
            self.client.get("/media/submissions/private.pdf").status_code, 404
        )

    def test_all_role_labels_retain_access_to_their_own_objects(self):
        for role in User.Role.values:
            self.owner.role = role
            self.owner.save()
            self.client.force_authenticate(self.owner)
            self.assertEqual(
                self.client.get(f"/api/courses/{self.course.pk}/").status_code, 200
            )
            self.assertEqual(self.client.get("/api/auth/me/").data["role"], role)
