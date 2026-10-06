from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from students.models import Student
from submissions.emailing import send_student_email

User = get_user_model()


class StudentNoticeEmailTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="lecturer@example.invalid")
        self.student = Student.objects.create(
            owner=user,
            student_number="00123456",
            first_name="Ava",
            last_name="Example",
            email="ava@example.invalid",
        )

    def test_direct_message_is_preserved_without_grading(self):
        send_student_email(self.student, "Synthetic notice", "Your class notice.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ava@example.invalid"])
        self.assertEqual(mail.outbox[0].body, "Your class notice.")

    def test_missing_address_is_rejected(self):
        self.student.email = ""
        with self.assertRaises(ValueError):
            send_student_email(self.student, "Synthetic notice", "Class notice.")


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
