from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission


class SubmissionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="teacher@example.com",
            password="testpass123",
        )

        self.course = Course.objects.create(
            owner=self.user,
            code="PHY101",
            name="Physics 101",
            year=2026,
            semester=1,
        )

        self.student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
        )

        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=self.student,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=100,
            weight=20,
        )

    def test_create_submission_without_enrollment(self):
        uploaded_file = SimpleUploadedFile(
            "test.pdf",
            b"fake pdf content",
            content_type="application/pdf",
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=uploaded_file,
            original_filename="test.pdf",
        )

        self.assertEqual(submission.assessment, self.assessment)
        self.assertIsNone(submission.enrollment)
        self.assertEqual(submission.original_filename, "test.pdf")

    def test_submission_can_be_matched_to_enrollment(self):
        uploaded_file = SimpleUploadedFile(
            "test.pdf",
            b"fake pdf content",
            content_type="application/pdf",
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=self.enrollment,
            file=uploaded_file,
            original_filename="test.pdf",
        )

        self.assertEqual(submission.enrollment, self.enrollment)

    def test_submission_string_representation(self):
        uploaded_file = SimpleUploadedFile(
            "paper.pdf",
            b"fake pdf content",
            content_type="application/pdf",
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=uploaded_file,
            original_filename="paper.pdf",
        )

        self.assertEqual(str(submission), "paper.pdf")


class SubmissionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

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

        self.other_course = Course.objects.create(
            owner=self.other_user,
            name="Chemistry 101",
            year=2026,
            semester=1,
        )

        self.assessment = Assessment.objects.create(
            course=self.course,
            name="Test 1",
            max_mark=100,
            weight=20,
        )

        self.other_assessment = Assessment.objects.create(
            course=self.other_course,
            name="Test 1",
            max_mark=100,
            weight=20,
        )

        self.client.force_authenticate(user=self.user)

    def test_upload_submission(self):
        uploaded_file = SimpleUploadedFile(
            "student-paper.pdf",
            b"fake pdf content",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.assessment.id,
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Submission.objects.count(), 1)

        submission = Submission.objects.first()

        self.assertEqual(submission.assessment, self.assessment)
        self.assertEqual(
            submission.original_filename,
            "student-paper.pdf",
        )
        self.assertIsNone(submission.enrollment)

    def test_cannot_upload_to_another_users_assessment(self):
        uploaded_file = SimpleUploadedFile(
            "student-paper.pdf",
            b"fake pdf content",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/submissions/",
            {
                "assessment": self.other_assessment.id,
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(Submission.objects.count(), 0)

    def test_list_only_own_submissions(self):
        own_submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "own.pdf",
                b"own",
                content_type="application/pdf",
            ),
            original_filename="own.pdf",
        )

        Submission.objects.create(
            assessment=self.other_assessment,
            file=SimpleUploadedFile(
                "other.pdf",
                b"other",
                content_type="application/pdf",
            ),
            original_filename="other.pdf",
        )

        response = self.client.get("/api/submissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], own_submission.id)

    def test_can_match_submission_to_enrollment(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="12345678",
            first_name="Test",
            last_name="Student",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        response = self.client.patch(
            f"/api/submissions/{submission.id}/",
            {
                "enrollment": enrollment.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        submission.refresh_from_db()

        self.assertEqual(submission.enrollment, enrollment)

    def test_cannot_match_submission_to_enrollment_from_other_course(self):
        other_owned_course = Course.objects.create(
            owner=self.user,
            code="MAT101",
            name="Maths 101",
            year=2026,
            semester=1,
        )

        student = Student.objects.create(
            owner=self.user,
            student_number="87654321",
            first_name="Other",
            last_name="Student",
        )

        wrong_enrollment = Enrollment.objects.create(
            course=other_owned_course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        response = self.client.patch(
            f"/api/submissions/{submission.id}/",
            {
                "enrollment": wrong_enrollment.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        submission.refresh_from_db()

        self.assertIsNone(submission.enrollment)

    def test_cannot_match_submission_to_another_users_enrollment(self):
        other_student = Student.objects.create(
            owner=self.other_user,
            student_number="99999999",
            first_name="Other",
            last_name="Student",
        )

        other_enrollment = Enrollment.objects.create(
            course=self.other_course,
            student=other_student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        response = self.client.patch(
            f"/api/submissions/{submission.id}/",
            {
                "enrollment": other_enrollment.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        submission.refresh_from_db()

        self.assertIsNone(submission.enrollment)

    def test_can_create_result_from_matched_submission(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="11111111",
            first_name="Marked",
            last_name="Student",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=enrollment,
            file=SimpleUploadedFile(
                "marked.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="marked.pdf",
        )

        response = self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": 75},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        result = Result.objects.get(
            assessment=self.assessment,
            enrollment=enrollment,
        )

        self.assertEqual(result.mark, 75)

    def test_marking_submission_updates_existing_result(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="22222222",
            first_name="Existing",
            last_name="Student",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=enrollment,
            file=SimpleUploadedFile(
                "marked.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="marked.pdf",
        )

        Result.objects.create(
            assessment=self.assessment,
            enrollment=enrollment,
            mark=60,
        )

        response = self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": 80},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            Result.objects.filter(
                assessment=self.assessment,
                enrollment=enrollment,
            ).count(),
            1,
        )

        result = Result.objects.get(
            assessment=self.assessment,
            enrollment=enrollment,
        )

        self.assertEqual(result.mark, 80)

    def test_cannot_mark_unmatched_submission(self):
        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "unmatched.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="unmatched.pdf",
        )

        response = self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": 50},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(Result.objects.count(), 0)

    def test_cannot_enter_mark_above_max_mark(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="33333333",
            first_name="High",
            last_name="Mark",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=enrollment,
            file=SimpleUploadedFile(
                "marked.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="marked.pdf",
        )

        response = self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": 101},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(Result.objects.count(), 0)

    def test_cannot_mark_another_users_submission(self):
        other_student = Student.objects.create(
            owner=self.other_user,
            student_number="44444444",
            first_name="Other",
            last_name="Student",
        )

        other_enrollment = Enrollment.objects.create(
            course=self.other_course,
            student=other_student,
        )

        other_submission = Submission.objects.create(
            assessment=self.other_assessment,
            enrollment=other_enrollment,
            file=SimpleUploadedFile(
                "other.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="other.pdf",
        )

        response = self.client.post(
            f"/api/submissions/{other_submission.id}/mark/",
            {"mark": 50},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_new_submission_status_is_uploaded(self):
        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        self.assertEqual(
            submission.status,
            Submission.Status.UPLOADED,
        )

    def test_matching_submission_changes_status_to_matched(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="55555555",
            first_name="Matched",
            last_name="Student",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
        )

        response = self.client.patch(
            f"/api/submissions/{submission.id}/",
            {
                "enrollment": enrollment.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        submission.refresh_from_db()

        self.assertEqual(
            submission.status,
            Submission.Status.MATCHED,
        )

    def test_marking_submission_changes_status_to_marked(self):
        student = Student.objects.create(
            owner=self.user,
            student_number="66666666",
            first_name="Marked",
            last_name="Student",
        )

        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
        )

        submission = Submission.objects.create(
            assessment=self.assessment,
            enrollment=enrollment,
            file=SimpleUploadedFile(
                "paper.pdf",
                b"fake pdf content",
                content_type="application/pdf",
            ),
            original_filename="paper.pdf",
            status=Submission.Status.MATCHED,
        )

        response = self.client.post(
            f"/api/submissions/{submission.id}/mark/",
            {"mark": 70},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        submission.refresh_from_db()

        self.assertEqual(
            submission.status,
            Submission.Status.MARKED,
        )