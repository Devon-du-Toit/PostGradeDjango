"""List API behaviour shared by every list endpoint (#11): pagination,
stable ordering, filters/search outside submissions, and query counts."""

from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from distribution.services import schedule_result_email
from students.models import Enrollment, Student
from submissions.models import Submission


class ListAPITestData:
    @classmethod
    def setUpTestData(cls):
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
            year=2026,
            semester=2,
        )
        cls.old_course = Course.objects.create(
            owner=cls.owner,
            code="STTN111",
            name="Statistics",
            year=2025,
            semester=1,
        )
        cls.other_course = Course.objects.create(
            owner=cls.other_user,
            code="HIST101",
            name="History",
            year=2026,
            semester=2,
        )

        cls.sipho = Student.objects.create(
            owner=cls.owner,
            student_number="30451234",
            first_name="Sipho",
            last_name="Dlamini",
            email="sipho@example.com",
        )
        cls.anna = Student.objects.create(
            owner=cls.owner,
            student_number="31112222",
            first_name="Anna",
            last_name="Botha",
            email="",
        )
        cls.other_student = Student.objects.create(
            owner=cls.other_user,
            student_number="99990000",
            first_name="Zed",
            last_name="Other",
            email="zed@example.com",
        )

        cls.sipho_enrollment = Enrollment.objects.create(
            course=cls.course,
            student=cls.sipho,
        )
        cls.anna_enrollment = Enrollment.objects.create(
            course=cls.course,
            student=cls.anna,
        )
        Enrollment.objects.create(course=cls.old_course, student=cls.anna)

        cls.assessment = Assessment.objects.create(
            course=cls.course,
            name="Class Test 1",
            max_mark=Decimal("50.00"),
            weight=Decimal("10.00"),
        )
        Assessment.objects.create(
            course=cls.course,
            name="Exam",
            max_mark=Decimal("100.00"),
            weight=Decimal("50.00"),
        )

        sipho_result = Result.objects.create(
            assessment=cls.assessment,
            enrollment=cls.sipho_enrollment,
            mark=Decimal("40.00"),
        )
        anna_result = Result.objects.create(
            assessment=cls.assessment,
            enrollment=cls.anna_enrollment,
            mark=Decimal("30.00"),
        )
        # Sipho's email is queued; Anna has no address, so hers fails.
        schedule_result_email(sipho_result)
        schedule_result_email(anna_result)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data


class PaginationTests(ListAPITestData, TestCase):
    def create_courses(self, count):
        Course.objects.bulk_create(
            Course(
                owner=self.owner,
                code=f"BULK{number:03d}",
                name="Bulk",
                year=2020,
                semester=1,
            )
            for number in range(count)
        )

    def test_list_returns_pagination_envelope(self):
        data = self.get("/api/courses/")

        self.assertEqual(
            set(data),
            {"count", "next", "previous", "results"},
        )
        self.assertEqual(data["count"], 2)

    def test_default_page_size_is_25(self):
        self.create_courses(30)

        data = self.get("/api/courses/")

        self.assertEqual(data["count"], 32)
        self.assertEqual(len(data["results"]), 25)
        self.assertIsNotNone(data["next"])
        self.assertIsNone(data["previous"])

    def test_page_size_parameter_is_capped_at_100(self):
        self.create_courses(101)

        self.assertEqual(
            len(self.get("/api/courses/?page_size=5")["results"]),
            5,
        )
        self.assertEqual(
            len(self.get("/api/courses/?page_size=500")["results"]),
            100,
        )

    def test_pages_do_not_overlap_or_skip(self):
        # Same year and semester, so the order relies on code and id.
        self.create_courses(30)
        seen = []
        page = 1

        while True:
            data = self.get(f"/api/courses/?page_size=7&page={page}")
            seen.extend(course["id"] for course in data["results"])
            if data["next"] is None:
                break
            page += 1

        self.assertEqual(len(seen), 32)
        self.assertEqual(len(set(seen)), 32)

    def test_page_past_the_end_returns_404(self):
        response = self.client.get("/api/courses/?page=99")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_empty_list_has_zero_count(self):
        self.client.force_authenticate(
            user=User.objects.create_user(
                email="new@example.com",
                password="password123",
            )
        )

        data = self.get("/api/courses/")

        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])


class OrderingTests(ListAPITestData, TestCase):
    def test_courses_newest_term_first(self):
        codes = [c["code"] for c in self.get("/api/courses/")["results"]]

        self.assertEqual(codes, ["CMPG311", "STTN111"])

    def test_students_and_results_by_student_number(self):
        students = self.get("/api/students/")["results"]
        results = self.get(
            f"/api/assessments/{self.assessment.id}/results/"
        )["results"]

        self.assertEqual(
            [s["student_number"] for s in students],
            ["30451234", "31112222"],
        )
        self.assertEqual(
            [r["student_number"] for r in results],
            ["30451234", "31112222"],
        )


class ListFilterTests(ListAPITestData, TestCase):
    def assert_invalid(self, url, field):
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(field, response.data)
        return response.data[field]

    def codes(self, url):
        return [c["code"] for c in self.get(url)["results"]]

    def test_course_filters_and_search(self):
        self.assertEqual(self.codes("/api/courses/?year=2026"), ["CMPG311"])
        self.assertEqual(
            self.codes("/api/courses/?year=2025&semester=1"),
            ["STTN111"],
        )
        self.assertEqual(
            self.codes("/api/courses/?search=software"),
            ["CMPG311"],
        )
        self.assertEqual(self.codes("/api/courses/?year=2024"), [])

    def test_invalid_number_is_rejected(self):
        self.assert_invalid("/api/courses/?year=abc", "year")

    def test_unknown_parameters_are_ignored(self):
        self.assertEqual(len(self.codes("/api/courses/?foo=1")), 2)

    def test_students_filtered_by_course(self):
        data = self.get(f"/api/students/?course={self.old_course.id}")

        self.assertEqual(
            [s["student_number"] for s in data["results"]],
            ["31112222"],
        )

    def test_other_owners_ids_are_rejected_like_missing_ones(self):
        foreign = self.assert_invalid(
            f"/api/students/?course={self.other_course.id}",
            "course",
        )
        missing = self.assert_invalid(
            "/api/students/?course=999999",
            "course",
        )

        self.assertEqual(foreign, missing)
        self.assert_invalid(
            f"/api/enrollments/?student={self.other_student.id}",
            "student",
        )

    def test_search_requires_every_word_to_match(self):
        both = self.get("/api/students/?search=sipho 3045")["results"]
        mixed = self.get("/api/students/?search=sipho botha")["results"]

        self.assertEqual([s["first_name"] for s in both], ["Sipho"])
        self.assertEqual(mixed, [])

    def test_search_never_returns_other_owners_students(self):
        data = self.get("/api/students/?search=zed")

        self.assertEqual(data["count"], 0)

    def test_enrollment_filters_and_search(self):
        by_course = self.get(f"/api/enrollments/?course={self.course.id}")
        by_name = self.get("/api/enrollments/?search=dlamini")

        self.assertEqual(by_course["count"], 2)
        self.assertEqual(
            [e["id"] for e in by_name["results"]],
            [self.sipho_enrollment.id],
        )

    def test_course_student_and_assessment_search(self):
        students = self.get(
            f"/api/courses/{self.course.id}/students/?search=anna"
        )
        assessments = self.get(
            f"/api/courses/{self.course.id}/assessments/?search=test"
        )

        self.assertEqual(
            [s["student_number"] for s in students["results"]],
            ["31112222"],
        )
        self.assertEqual(
            [a["name"] for a in assessments["results"]],
            ["Class Test 1"],
        )

    def test_result_search_by_student(self):
        data = self.get(
            f"/api/assessments/{self.assessment.id}/results/?search=botha"
        )

        self.assertEqual(
            [r["student_name"] for r in data["results"]],
            ["Anna Botha"],
        )

    def test_result_email_status_filter_and_search(self):
        url = f"/api/assessments/{self.assessment.id}/result-emails/"

        failed = self.get(f"{url}?status=failed")
        queued_or_sent = self.get(f"{url}?status=queued,sent")
        by_recipient = self.get(f"{url}?search=sipho@")

        self.assertEqual(
            [e["student_number"] for e in failed["results"]],
            ["31112222"],
        )
        self.assertEqual(
            [e["student_number"] for e in queued_or_sent["results"]],
            ["30451234"],
        )
        self.assertEqual(by_recipient["count"], 1)
        self.assert_invalid(f"{url}?status=nope", "status")


class ListQueryCountTests(ListAPITestData, TestCase):
    """Each list costs the same number of queries at any size.

    count + page (+ owner lookup for nested lists)
    (+ 2 recognition prefetches for submissions).
    """

    def endpoints(self):
        return {
            "/api/courses/": 2,
            "/api/students/": 2,
            "/api/enrollments/": 2,
            f"/api/courses/{self.course.id}/students/": 3,
            f"/api/courses/{self.course.id}/assessments/": 3,
            f"/api/assessments/{self.assessment.id}/results/": 3,
            f"/api/assessments/{self.assessment.id}/result-emails/": 3,
            "/api/submissions/": 4,
            "/api/submissions/verification-queue/": 4,
        }

    def add_rows(self, start, count):
        for number in range(start, start + count):
            student = Student.objects.create(
                owner=self.owner,
                student_number=f"4{number:07d}",
                first_name="Extra",
                last_name=f"Student{number}",
                email=f"extra{number}@example.com",
            )
            enrollment = Enrollment.objects.create(
                course=self.course,
                student=student,
            )
            result = Result.objects.create(
                assessment=self.assessment,
                enrollment=enrollment,
                mark=Decimal("25.00"),
            )
            schedule_result_email(result)
            Submission.objects.create(
                assessment=self.assessment,
                enrollment=enrollment,
                file=f"submissions/tests/extra{number}.pdf",
                original_filename=f"extra{number}.pdf",
                status=Submission.Status.NEEDS_VERIFICATION,
            )
            Course.objects.create(
                owner=self.owner,
                code=f"EXTRA{number}",
                name="Extra",
                year=2024,
                semester=1,
            )

    def assert_query_counts(self):
        for url, expected in self.endpoints().items():
            with self.subTest(url=url):
                with self.assertNumQueries(expected):
                    response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_query_counts_do_not_grow_with_rows(self):
        self.add_rows(start=0, count=1)
        self.assert_query_counts()

        self.add_rows(start=1, count=10)
        self.assert_query_counts()
