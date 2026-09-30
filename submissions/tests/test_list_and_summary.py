from rest_framework.test import APITestCase

from accounts.models import User
from assessments.models import Assessment, Result
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission

LIST_URL = "/api/submissions/"
SUMMARY_URL = "/api/submissions/summary/"
PROGRESS_URL = "/api/assessments/progress/"


class Base(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="lecturer.a@test.com", password="pw12345!")
        self.bob = User.objects.create_user(email="lecturer.b@test.com", password="pw12345!")

        self.course_a = Course.objects.create(owner=self.alice, code="CS101", name="Intro", year=2026, semester=1)
        self.course_a2 = Course.objects.create(owner=self.alice, code="CS102", name="Data", year=2026, semester=1)
        self.course_b = Course.objects.create(owner=self.bob, code="BB100", name="Other", year=2026, semester=1)

        self.assess_a = self._assessment(self.course_a, "Assignment 1")
        self.assess_a2 = self._assessment(self.course_a2, "Test 1")
        self.assess_b = self._assessment(self.course_b, "Bob's test")

        self.enr_smith = self._enrollment(self.alice, self.course_a, "1001", "Alice", "Smith")
        self.enr_jones = self._enrollment(self.alice, self.course_a, "1002", "Bob", "Jones")

    def _assessment(self, course, name):
        return Assessment.objects.create(course=course, name=name, max_mark=100, weight=10)

    def _enrollment(self, owner, course, number, first, last):
        student = Student.objects.create(
            owner=owner, student_number=number, first_name=first, last_name=last, email=f"{number}@test.com"
        )
        return Enrollment.objects.create(course=course, student=student)

    def _submission(self, assessment, status="uploaded", enrollment=None, name="script.pdf"):
        return Submission.objects.create(assessment=assessment, enrollment=enrollment, original_filename=name, status=status)

    def _ids(self, response):
        return [row["id"] for row in response.data["results"]]


class FilterTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.alice)
        self.s_matched = self._submission(self.assess_a, "matched", self.enr_smith)
        self.s_needs = self._submission(self.assess_a, "needs_verification")
        self.s_other_course = self._submission(self.assess_a2, "matched", self.enr_jones)

    def test_filter_by_status(self):
        r = self.client.get(LIST_URL, {"status": "matched", "page_size": 10})
        self.assertEqual(r.status_code, 200)
        self.assertCountEqual(self._ids(r), [self.s_matched.id, self.s_other_course.id])

    def test_filter_by_course(self):
        r = self.client.get(LIST_URL, {"course": self.course_a.id, "page_size": 10})
        self.assertCountEqual(self._ids(r), [self.s_matched.id, self.s_needs.id])

    def test_filter_by_assessment(self):
        r = self.client.get(LIST_URL, {"assessment": self.assess_a2.id, "page_size": 10})
        self.assertEqual(self._ids(r), [self.s_other_course.id])

    def test_search_by_student_number_and_name(self):
        self.assertEqual(self._ids(self.client.get(LIST_URL, {"search": "1001", "page_size": 10})), [self.s_matched.id])
        self.assertEqual(self._ids(self.client.get(LIST_URL, {"search": "smith", "page_size": 10})), [self.s_matched.id])

    def test_combined_filters(self):
        r = self.client.get(LIST_URL, {"course": self.course_a.id, "status": "matched", "search": "smith", "page_size": 10})
        self.assertEqual(self._ids(r), [self.s_matched.id])

    def test_combination_with_no_matches_is_empty_200(self):
        r = self.client.get(LIST_URL, {"course": self.course_a.id, "status": "marked", "page_size": 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"], [])

    def test_no_paging_params_returns_paginated_response(self):
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, 200)
        self.assertIn("results", r.data)
        self.assertEqual(r.data["count"], 3)


class InvalidFilterTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.alice)

    def test_invalid_values_return_400(self):
        cases = [
            ("status", "banana"),
            ("course", "abc"),
            ("course", "1.5"),
            ("course", "999999"),
            ("assessment", "abc"),
            ("assessment", "999999"),
            ("ordering", "banana"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                r = self.client.get(LIST_URL, {field: value, "page_size": 10})
                self.assertEqual(r.status_code, 400)


class PaginationOrderingTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.alice)
        self.created = [self._submission(self.assess_a, "uploaded", name=f"s{i}.pdf") for i in range(105)]

    def test_default_page_size_is_20(self):
        r = self.client.get(LIST_URL)
        self.assertEqual(len(r.data["results"]), 20)
        self.assertEqual(r.data["count"], 105)

    def test_pages_do_not_overlap_or_skip(self):
        seen = []
        for page in range(1, 12):
            r = self.client.get(LIST_URL, {"page": page, "page_size": 10})
            self.assertEqual(r.status_code, 200)
            seen += self._ids(r)
        self.assertEqual(len(seen), 105)
        self.assertEqual(len(set(seen)), 105)

    def test_order_stable_when_timestamps_tie(self):
        Submission.objects.update(created_at=self.created[0].created_at)
        first = self._ids(self.client.get(LIST_URL, {"page_size": 30}))
        second = self._ids(self.client.get(LIST_URL, {"page_size": 30}))
        self.assertEqual(first, second)

    def test_page_past_the_end_returns_empty_results(self):
        r = self.client.get(LIST_URL, {"page": 99, "page_size": 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 105)
        self.assertEqual(r.data["results"], [])

    def test_page_size_capped_at_100(self):
        r = self.client.get(LIST_URL, {"page_size": 1000})
        self.assertEqual(len(r.data["results"]), 100)


class IsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.enr_bob = self._enrollment(self.bob, self.course_b, "9001", "Zed", "Zulu")
        self.bobs_sub = self._submission(self.assess_b, "matched", self.enr_bob)
        self.alices_sub = self._submission(self.assess_a, "matched", self.enr_smith)

    def test_list_never_returns_other_owners_rows(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(LIST_URL, {"page_size": 50})
        self.assertNotIn(self.bobs_sub.id, self._ids(r))

    def test_cannot_filter_by_other_owners_course_or_assessment(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get(LIST_URL, {"course": self.course_b.id, "page_size": 10}).status_code, 400)
        self.assertEqual(self.client.get(LIST_URL, {"assessment": self.assess_b.id, "page_size": 10}).status_code, 400)

    def test_search_does_not_leak_other_owners_students(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(LIST_URL, {"search": "9001", "page_size": 10})
        self.assertEqual(r.data["results"], [])

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)


class SummaryTests(Base):
    def test_pending_verification_counts(self):
        self._submission(self.assess_a, "needs_verification")
        self._submission(self.assess_a, "matched", self.enr_smith)
        self._submission(self.assess_a, "verified", self.enr_jones)     # not pending
        self._submission(self.assess_b, "needs_verification")           # Bob's — must not count
        self.client.force_authenticate(self.alice)
        r = self.client.get(SUMMARY_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["needs_verification"], 1)
        self.assertEqual(r.data["matched"], 1)
        self.assertEqual(r.data["pending_verification"], 2)

    def test_summary_with_no_data_is_zero(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(SUMMARY_URL)
        self.assertEqual(r.data["pending_verification"], 0)

    def test_summary_accepts_owned_course_without_assessments(self):
        empty_course = Course.objects.create(
            owner=self.alice,
            code="CS103",
            name="Empty",
            year=2026,
            semester=1,
        )
        self.client.force_authenticate(self.alice)
        r = self.client.get(SUMMARY_URL, {"course": empty_course.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["pending_verification"], 0)

    def test_summary_rejects_other_owners_course(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(SUMMARY_URL, {"course": self.course_b.id})
        self.assertEqual(r.status_code, 400)

    def test_assessment_progress_numbers(self):
        Result.objects.create(assessment=self.assess_a, enrollment=self.enr_smith, mark=50)
        self.client.force_authenticate(self.alice)
        r = self.client.get(PROGRESS_URL, {"course": self.course_a.id})
        self.assertEqual(r.status_code, 200, r.data)
        row = next(x for x in r.data if x["assessment_id"] == self.assess_a.id)
        self.assertEqual(row["enrolled_count"], 2)
        self.assertEqual(row["marked_count"], 1)
        self.assertEqual(row["remaining_count"], 1)
        self.assertEqual(row["percent_complete"], 50.0)

    def test_progress_zero_enrolled_no_divide_by_zero(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(PROGRESS_URL, {"course": self.course_a2.id})
        self.assertEqual(r.status_code, 200, r.data)
        row = next(x for x in r.data if x["assessment_id"] == self.assess_a2.id)
        self.assertEqual(row["percent_complete"], 0.0)

    def test_progress_excludes_other_owners_assessments(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(PROGRESS_URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn(self.assess_b.id, [x["assessment_id"] for x in r.data])

    def test_progress_rejects_invalid_or_other_owner_course(self):
        self.client.force_authenticate(self.alice)
        for course_id in ("abc", self.course_b.id):
            with self.subTest(course_id=course_id):
                r = self.client.get(PROGRESS_URL, {"course": course_id})
                self.assertEqual(r.status_code, 400)