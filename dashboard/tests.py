import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission


class DashboardTestData:
    @classmethod
    def setUpTestData(cls):
        cls.this_year = timezone.localdate().year
        cls.owner = User.objects.create_user(
            email="owner@example.com",
            password="password123",
        )
        cls.other_user = User.objects.create_user(
            email="other@example.com",
            password="password123",
        )

        cls.course = Course.objects.create(
            owner=cls.owner,
            code="CMPG311",
            name="Software Engineering",
            year=cls.this_year,
            semester=2,
        )
        Course.objects.create(
            owner=cls.owner,
            code="CMPG111",
            name="Programming",
            year=cls.this_year,
            semester=1,
        )
        Course.objects.create(
            owner=cls.owner,
            code="STTN111",
            name="Statistics",
            year=cls.this_year - 1,
            semester=1,
        )
        cls.other_course = Course.objects.create(
            owner=cls.other_user,
            code="HIST101",
            name="History",
            year=cls.this_year,
            semester=2,
        )

        cls.enrollments = [
            Enrollment.objects.create(
                course=cls.course,
                student=Student.objects.create(
                    owner=cls.owner,
                    student_number=f"3000000{number}",
                    first_name="Student",
                    last_name=str(number),
                    email=f"student{number}@example.com",
                ),
            )
            for number in range(4)
        ]

        cls.test_one = Assessment.objects.create(
            course=cls.course,
            name="Class Test 1",
            date=datetime.date(2026, 9, 1),
        )
        cls.test_two = Assessment.objects.create(
            course=cls.course,
            name="Class Test 2",
            date=datetime.date(2026, 9, 20),
        )
        cls.undated = Assessment.objects.create(
            course=cls.course,
            name="Project",
        )
        cls.other_assessment = Assessment.objects.create(
            course=cls.other_course,
            name="Essay",
        )

        statuses = [
            Submission.Status.MATCHED,
            Submission.Status.NEEDS_VERIFICATION,
            Submission.Status.VERIFIED,
            Submission.Status.VERIFIED,
        ]
        for enrollment, submission_status in zip(cls.enrollments, statuses):
            cls.add_submission(cls.test_one, submission_status, enrollment)
        # Entered in the gradebook without a script.

        for submission_status in [
            Submission.Status.NEEDS_VERIFICATION,
            Submission.Status.MATCHED,
            Submission.Status.MATCHED,
        ]:
            cls.add_submission(cls.other_assessment, submission_status)

    @classmethod
    def add_submission(cls, assessment, submission_status, enrollment=None):
        return Submission.objects.create(
            assessment=assessment,
            enrollment=enrollment,
            # A stored name only: these tests never read the file.
            file="submissions/tests/script.pdf",
            original_filename="script.pdf",
            status=submission_status,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)


class DashboardStatsTests(DashboardTestData, TestCase):
    url = "/api/dashboard/stats/"

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_active_courses_are_own_courses_this_year(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["active_courses"], 2)

    def test_pending_verifications_match_the_queue(self):
        stats = self.client.get(self.url).data
        queue = self.client.get("/api/submissions/verification-queue/").data

        self.assertEqual(stats["pending_verifications"], 2)
        self.assertEqual(stats["pending_verifications"], queue["count"])

    def test_counts_every_status_and_excludes_other_owners(self):
        by_status = self.client.get(self.url).data["submissions_by_status"]

        self.assertEqual(set(by_status), set(Submission.Status.values))
        self.assertEqual(by_status[Submission.Status.MATCHED], 1)
        self.assertEqual(by_status[Submission.Status.NEEDS_VERIFICATION], 1)
        self.assertEqual(by_status[Submission.Status.VERIFIED], 2)
        self.assertEqual(by_status[Submission.Status.UPLOADED], 0)

    def test_new_lecturer_gets_zeros(self):
        self.client.force_authenticate(
            user=User.objects.create_user(
                email="new@example.com",
                password="password123",
            )
        )

        data = self.client.get(self.url).data

        self.assertEqual(data["active_courses"], 0)
        self.assertEqual(data["pending_verifications"], 0)
        self.assertEqual(set(data["submissions_by_status"].values()), {0})

    def test_uses_two_queries(self):
        with self.assertNumQueries(2):
            self.client.get(self.url)


class DashboardAssessmentProgressTests(DashboardTestData, TestCase):
    url = "/api/dashboard/assessments/"

    def rows(self, query=""):
        response = self.client.get(f"{self.url}{query}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["results"]

    def test_newest_first_with_undated_last(self):
        names = [row["name"] for row in self.rows()]

        self.assertEqual(names, ["Class Test 2", "Class Test 1", "Project"])

    def test_progress_counts(self):
        row = next(row for row in self.rows() if row["id"] == self.test_one.id)

        self.assertEqual(row["course_code"], "CMPG311")
        self.assertEqual(row["enrolled"], 4)
        self.assertEqual(row["submissions"], 4)
        self.assertEqual(
            row["submissions_by_status"][Submission.Status.VERIFIED],
            2,
        )
        # Two marked scripts plus one mark entered without a script.

    def test_assessment_without_scripts_has_zero_counts(self):
        row = next(row for row in self.rows() if row["id"] == self.undated.id)

        self.assertEqual(row["enrolled"], 4)
        self.assertEqual(row["submissions"], 0)

        self.assertEqual(set(row["submissions_by_status"].values()), {0})

    def test_other_owners_assessments_are_excluded_and_rejected(self):
        ids = {row["id"] for row in self.rows()}
        response = self.client.get(f"{self.url}?course={self.other_course.id}")

        self.assertNotIn(self.other_assessment.id, ids)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_course_filter_and_search(self):
        self.assertEqual(len(self.rows(f"?course={self.course.id}")), 3)
        self.assertEqual(
            [row["name"] for row in self.rows("?search=project")],
            ["Project"],
        )
        self.assertEqual(len(self.rows("?search=cmpg311")), 3)

    def test_query_count_does_not_grow_with_assessments(self):
        with self.assertNumQueries(3):
            self.client.get(self.url)

        for number in range(5):
            assessment = Assessment.objects.create(
                course=self.course,
                name=f"Extra {number}",
            )
            self.add_submission(assessment, Submission.Status.UPLOADED)

        with self.assertNumQueries(3):
            self.client.get(self.url)
