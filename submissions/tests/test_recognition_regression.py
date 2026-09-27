from django.test import SimpleTestCase

from submissions.recognition.matching import (
    find_best_student_number_match,
)
from submissions.recognition.types import (
    StudentNumberCandidate,
)


class RecognitionRegressionTests(SimpleTestCase):
    def test_exact_number_regression_cases(self): #exact number regression
        valid_student_numbers = [
            "12345678",
            "23456789",
            "34567890",
            "45678901",
        ]

        cases = [
            ("12345678", "12345678"),
            ("23456789", "23456789"),
            ("34567890", "34567890"),
            ("45678901", "45678901"),
        ]

        for candidate_value, expected_number in cases:
            candidate = StudentNumberCandidate(
                value=candidate_value,
                confidence=0.95,
            )

            match = find_best_student_number_match(
                candidates=[candidate],
                valid_student_numbers=valid_student_numbers,
            )

            self.assertEqual(
                match,
                expected_number,
            )
    #synthetic numbers that don't belong to any valid student
    # false number regression
    def test_false_match_regression_cases(self):
        valid_student_numbers = [
            "12345678",
            "23456789",
            "34567890",
            "45678901",
        ]

        cases = [
            "99999999",
            "11111111",
            "87654321",
        ]

        false_matches = 0

        for candidate_value in cases:
            candidate = StudentNumberCandidate(
                value=candidate_value,
                confidence=0.95,
            )

            match = find_best_student_number_match(
                candidates=[candidate],
                valid_student_numbers=valid_student_numbers,
            )

            if match is not None:
                false_matches += 1

        self.assertEqual(
            false_matches,
            0,
            (
                "Recognition regression: "
                f"{false_matches} false match(es) detected"
            ),
        )
    #metrics test
    def test_recognition_regression_metrics(self):
        valid_student_numbers = [
            "12345678",
            "23456789",
            "34567890",
            "45678901",
        ]

        exact_cases = [
            "12345678",
            "23456789",
            "34567890",
            "45678901",
        ]

        no_match_cases = [
            "99999999",
            "11111111",
            "87654321",
        ]

        exact_matches = 0
        false_matches = 0

        for student_number in exact_cases:
            candidate = StudentNumberCandidate(
                value=student_number,
                confidence=0.95,
            )

            match = find_best_student_number_match(
                candidates=[candidate],
                valid_student_numbers=valid_student_numbers,
            )

            if match == student_number:
                exact_matches += 1

        for candidate_value in no_match_cases:
            candidate = StudentNumberCandidate(
                value=candidate_value,
                confidence=0.95,
            )

            match = find_best_student_number_match(
                candidates=[candidate],
                valid_student_numbers=valid_student_numbers,
            )

            if match is not None:
                false_matches += 1


        self.assertEqual(
            exact_matches,
            len(exact_cases),
            "Exact-number recognition regressed",
        )

        self.assertEqual(
            false_matches,
            0,
            "False-match recognition regressed",
        )
    def test_ambiguous_student_number_returns_no_match(self):
        valid_student_numbers = [
            "12345678",
            "12345679",
        ]

        candidate = StudentNumberCandidate(
            value="12345670",
            confidence=0.95,
        )

        match = find_best_student_number_match(
            candidates=[candidate],
            valid_student_numbers=valid_student_numbers,
        )

        self.assertIsNone(match) 

    def test_multiple_possible_candidate_matches_return_no_match(self):
        valid_student_numbers = [
            "12345678",
            "87654321",
        ]

        candidates = [
            StudentNumberCandidate(
                value="12345670",
                confidence=0.95,
            ),
            StudentNumberCandidate(
                value="87654320",
                confidence=0.95,
            ),
        ]

        match = find_best_student_number_match(
            candidates=candidates,
            valid_student_numbers=valid_student_numbers,
        )

        self.assertIsNone(match)   