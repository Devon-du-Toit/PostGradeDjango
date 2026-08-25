from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase

from students.models import Student

from django.urls import reverse


User = get_user_model()


class StudentEmailAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="lecturer@example.com",
            password="testpass123",
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )

        self.url = reverse(
            "student-email",
            kwargs={"pk": self.student.id},
        )

        self.client.force_authenticate(user=self.user)

    def test_owner_can_email_student(self):
        response = self.client.post(
            self.url,
            {
                "subject": "Hello",
                "message": "Test message",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(
            mail.outbox[0].to,
            ["alice@example.com"],
        )

    def test_cannot_email_another_users_student(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )

        self.student.owner = other_user
        self.student.save()

        response = self.client.post(
            self.url,
            {
                "subject": "Hello",
                "message": "Test message",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_subject_is_required(self):
        response = self.client.post(
            self.url,
            {
                "message": "Test message",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_message_is_required(self):
        response = self.client.post(
            self.url,
            {
                "subject": "Hello",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(len(mail.outbox), 0)