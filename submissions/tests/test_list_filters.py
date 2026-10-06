from rest_framework.test import APITestCase

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from students.models import Enrollment, Student
from submissions.models import Submission

LIST_URL = "/api/submissions/"
QUEUE_URL = "/api/submissions/verification-queue/"


class Base(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            email="lecturer.a@test.com", password="pw12345!"
        )
        self.bob = User.objects.create_user(
            email="lecturer.b@test.com", password="pw12345!"
        )

        self.course_a = Course.objects.create(
            owner=self.alice, code="CS101", name="Intro", year=2026, semester=1
        )
        self.course_a2 = Course.objects.create(
            owner=self.alice, code="CS102", name="Data", year=2026, semester=1
        )
        self.course_b = Course.objects.create(
            owner=self.bob, code="BB100", name="Other", year=2026, semester=1
        )

        self.assess_a = self._assessment(self.course_a, "Assignment 1")
        self.assess_a2 = self._assessment(self.course_a2, "Test 1")
        self.assess_b = self._assessment(self.course_b, "Bob's test")

        self.enr_smith = self._enrollment(
            self.alice, self.course_a, "1001", "Alice", "Smith"
        )
        self.enr_jones = self._enrollment(
            self.alice, self.course_a, "1002", "Bob", "Jones"
        )

    def _assessment(self, course, name):
        return Assessment.objects.create(course=course, name=name)

    def _enrollment(self, owner, course, number, first, last):
        student = Student.objects.create(
            owner=owner,
            student_number=number,
            first_name=first,
            last_name=last,
            email=f"{number}@test.com",
        )
        return Enrollment.objects.create(course=course, student=student)

    def _submission(self, assessment, status, enrollment=None, name="script.pdf"):
        return Submission.objects.create(
            assessment=assessment,
            enrollment=enrollment,
            original_filename=name,
            status=status,
        )

    def _ids(self, response):
        return [row["id"] for row in response.data["results"]]


class SubmissionListFilterTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.alice)
        self.s_matched = self._submission(
            self.assess_a, Submission.Status.MATCHED, self.enr_smith
        )
        self.s_needs = self._submission(
            self.assess_a, Submission.Status.NEEDS_VERIFICATION
        )
        self.s_verified = self._submission(
            self.assess_a, Submission.Status.VERIFIED, self.enr_jones
        )
        self.s_processing = self._submission(
            self.assess_a, Submission.Status.PROCESSING
        )
        self.s_failed = self._submission(
            self.assess_a, Submission.Status.RECOGNITION_FAILED
        )
        # The same student can join both courses; a submission must use its
        # assessment course's enrollment, rather than the first course's link.
        other_enrollment = Enrollment.objects.create(
            course=self.course_a2, student=self.enr_jones.student
        )
        self.s_other_course = self._submission(
            self.assess_a2, Submission.Status.MATCHED, other_enrollment
        )

    def test_filter_by_single_status(self):
        r = self.client.get(
            LIST_URL, {"status": Submission.Status.MATCHED, "page_size": 20}
        )
        self.assertEqual(r.status_code, 200)
        self.assertCountEqual(self._ids(r), [self.s_matched.id, self.s_other_course.id])

    def test_filter_by_comma_separated_status(self):
        value = f"{Submission.Status.MATCHED},{Submission.Status.VERIFIED}"
        r = self.client.get(LIST_URL, {"status": value, "page_size": 20})
        self.assertEqual(r.status_code, 200)
        self.assertCountEqual(
            self._ids(r),
            [self.s_matched.id, self.s_verified.id, self.s_other_course.id],
        )

    def test_filter_by_course(self):
        r = self.client.get(LIST_URL, {"course": self.course_a.id, "page_size": 20})
        expected = [
            self.s_matched.id,
            self.s_needs.id,
            self.s_verified.id,
            self.s_processing.id,
            self.s_failed.id,
        ]
        self.assertCountEqual(self._ids(r), expected)

    def test_filter_by_assessment(self):
        r = self.client.get(
            LIST_URL, {"assessment": self.assess_a2.id, "page_size": 20}
        )
        self.assertEqual(self._ids(r), [self.s_other_course.id])

    def test_search_by_student_number(self):
        r = self.client.get(LIST_URL, {"search": "1001", "page_size": 20})
        self.assertEqual(self._ids(r), [self.s_matched.id])

    def test_search_by_student_name(self):
        r = self.client.get(LIST_URL, {"search": "smith", "page_size": 20})
        self.assertEqual(self._ids(r), [self.s_matched.id])

    def test_search_by_filename_finds_unmatched_submission(self):
        # s_needs has no enrollment, so only the filename can find it
        r = self.client.get(LIST_URL, {"search": "script.pdf", "page_size": 20})
        self.assertIn(self.s_needs.id, self._ids(r))

    def test_combined_filters(self):
        r = self.client.get(
            LIST_URL,
            {
                "course": self.course_a.id,
                "status": Submission.Status.MATCHED,
                "search": "smith",
                "page_size": 20,
            },
        )
        self.assertEqual(self._ids(r), [self.s_matched.id])

    def test_combination_with_no_matches_is_empty_200(self):
        r = self.client.get(
            LIST_URL,
            {
                "course": self.course_a2.id,
                "status": Submission.Status.VERIFIED,
                "page_size": 20,
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"], [])

    def test_invalid_single_status_returns_400(self):
        r = self.client.get(LIST_URL, {"status": "banana", "page_size": 20})
        self.assertEqual(r.status_code, 400)

    def test_invalid_value_inside_comma_list_returns_400_for_whole_request(self):
        # ChoiceInFilter validates every split value against choices, so one bad
        # value invalidates the entire filter — this is not a partial match.
        value = f"{Submission.Status.MATCHED},banana"
        r = self.client.get(LIST_URL, {"status": value, "page_size": 20})
        self.assertEqual(r.status_code, 400)

    def test_invalid_course_returns_400(self):
        r = self.client.get(LIST_URL, {"course": "abc", "page_size": 20})
        self.assertEqual(r.status_code, 400)

    def test_tied_timestamps_use_id_as_stable_tiebreaker(self):
        submission_ids = [
            self.s_matched.id,
            self.s_needs.id,
            self.s_verified.id,
            self.s_processing.id,
            self.s_failed.id,
            self.s_other_course.id,
        ]
        Submission.objects.update(created_at=self.s_matched.created_at)

        r = self.client.get(LIST_URL, {"page_size": 20})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._ids(r), sorted(submission_ids, reverse=True))


class SubmissionListIsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.enr_bob = self._enrollment(self.bob, self.course_b, "9001", "Zed", "Zulu")
        self.bobs_sub = self._submission(
            self.assess_b, Submission.Status.MATCHED, self.enr_bob
        )

    def test_list_never_returns_other_owners_rows(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(LIST_URL, {"page_size": 50})
        self.assertNotIn(self.bobs_sub.id, self._ids(r))

    def test_cannot_filter_by_other_owners_course_or_assessment(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(
            self.client.get(
                LIST_URL, {"course": self.course_b.id, "page_size": 20}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                LIST_URL, {"assessment": self.assess_b.id, "page_size": 20}
            ).status_code,
            400,
        )

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)


class SubmissionListEmptyTests(Base):
    def test_empty_table_first_page_is_200_with_empty_results(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(LIST_URL, {"page": 1, "page_size": 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"], [])
        self.assertEqual(r.data["count"], 0)

    def test_page_past_the_end_returns_404(self):
        self._submission(self.assess_a, Submission.Status.UPLOADED)
        self.client.force_authenticate(self.alice)
        r = self.client.get(LIST_URL, {"page": 99, "page_size": 10})
        self.assertEqual(r.status_code, 404)


class VerificationQueueTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.alice)
        self.s_needs = self._submission(
            self.assess_a, Submission.Status.NEEDS_VERIFICATION
        )
        self.s_matched = self._submission(
            self.assess_a, Submission.Status.MATCHED, self.enr_smith
        )
        self.s_verified = self._submission(
            self.assess_a, Submission.Status.VERIFIED, self.enr_jones
        )

    def test_queue_only_contains_pending_statuses(self):
        r = self.client.get(QUEUE_URL, {"page_size": 10})
        self.assertCountEqual(self._ids(r), [self.s_needs.id, self.s_matched.id])
        self.assertNotIn(self.s_verified.id, self._ids(r))

    def test_queue_filter_by_status_matched_only(self):
        r = self.client.get(
            QUEUE_URL, {"status": Submission.Status.MATCHED, "page_size": 10}
        )
        self.assertEqual(self._ids(r), [self.s_matched.id])

    def test_queue_status_outside_pending_set_returns_400(self):
        # VerificationQueueFilter's choices only include needs_verification/matched,
        # so "marked" is an invalid choice for this specific filter field.
        r = self.client.get(
            QUEUE_URL, {"status": Submission.Status.VERIFIED, "page_size": 10}
        )
        self.assertEqual(r.status_code, 400)

    def test_queue_respects_owner_scoping(self):
        other_enr = self._enrollment(self.bob, self.course_b, "9002", "Zoe", "Zed")
        bobs_pending = self._submission(
            self.assess_b, Submission.Status.NEEDS_VERIFICATION, other_enr
        )
        r = self.client.get(QUEUE_URL, {"page_size": 20})
        self.assertNotIn(bobs_pending.id, self._ids(r))

    def test_queue_empty_first_page(self):
        Submission.objects.all().delete()
        r = self.client.get(QUEUE_URL, {"page": 1, "page_size": 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"], [])
