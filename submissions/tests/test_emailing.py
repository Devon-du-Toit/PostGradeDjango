from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student
from submissions.emailing import (
    send_result_email,
    send_student_email,
)


User = get_user_model()


class ResultEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            name="Physics 101",
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
            max_mark=50,
            weight=20,
        )

        self.result = Result.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            mark=42,
        )

    def test_send_result_email(self):
        send_result_email(self.result)

        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]

        self.assertEqual(
            email.to,
            ["alice@example.com"],
        )

        self.assertIn(
            "Test 1",
            email.subject,
        )

        self.assertIn(
            "Alice",
            email.body,
        )

        self.assertIn(
            "42",
            email.body,
        )

        self.assertIn(
            "50",
            email.body,
        )

        self.assertIn(
            "84",
            email.body,
        )

    def test_send_result_email_requires_student_email(self):
        self.student.email = ""
        self.student.save()

        with self.assertRaises(ValueError):
            send_result_email(self.result)

        self.assertEqual(len(mail.outbox), 0)

class StudentEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Bob",
            last_name="Jones",
            email="bob@example.com",
        )

    def test_send_student_email(self):
        send_student_email(
            self.student,
            subject="Test email",
            message="Hello Bob",
        )

        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]

        self.assertEqual(
            email.to,
            ["bob@example.com"],
        )

        self.assertEqual(
            email.subject,
            "Test email",
        )

        self.assertEqual(
            email.body,
            "Hello Bob",
        )

    def test_send_student_email_requires_email_address(self):
        self.student.email = ""
        self.student.save()

        with self.assertRaises(ValueError):
            send_student_email(
                self.student,
                subject="Test email",
                message="Hello Bob",
            )

        self.assertEqual(len(mail.outbox), 0)