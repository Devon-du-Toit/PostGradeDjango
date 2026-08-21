from django.test import SimpleTestCase

from submissions.recognition.matching import (
    find_best_student_number_match,
)
from submissions.recognition.types import (
    StudentNumberCandidate,
)


class StudentNumberMatchingTests(SimpleTestCase):
    def test_exact_student_number_match(self):
        candidates = [
            StudentNumberCandidate(
                value="37279432",
                confidence=0.95,
            )
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37471899",
                "35226455",
            ],
        )

        self.assertEqual(
            match,
            "37279432",
        )

    def test_returns_none_when_no_exact_match(self):
        candidates = [
            StudentNumberCandidate(
                value="37279232",
                confidence=0.90,
            )
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37471899",
                "35226455",
            ],
            max_distance=0,
        )

        self.assertIsNone(match)

    def test_uses_later_exact_candidate(self):
        candidates = [
            StudentNumberCandidate(
                value="37279232",
                confidence=0.95,
            ),
            StudentNumberCandidate(
                value="37279432",
                confidence=0.80,
            ),
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37471899",
            ],
        )

        self.assertEqual(
            match,
            "37279432",
        )

    def test_matches_single_digit_error_when_unique(self):
        candidates = [
            StudentNumberCandidate(
                value="37279232",
                confidence=0.90,
            )
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37471899",
                "35226455",
            ],
        )

        self.assertEqual(
            match,
            "37279432",
        )

    def test_rejects_ambiguous_fuzzy_match(self):
        candidates = [
            StudentNumberCandidate(
                value="37279232",
                confidence=0.90,
            )
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37279234",
            ],
        )

        self.assertIsNone(match)

    def test_rejects_candidate_that_is_too_different(self):
        candidates = [
            StudentNumberCandidate(
                value="11111111",
                confidence=0.99,
            )
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=[
                "37279432",
                "37471899",
                "35226455",
            ],
        )

        self.assertIsNone(match)