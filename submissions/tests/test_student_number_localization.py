import re
from pathlib import Path

from django.test import SimpleTestCase

from submissions.recognition.localization import (
    find_student_number_text,
)


class StudentNumberLocalizationTests(SimpleTestCase):
    def setUp(self):
        self.fixture_dir = (
            Path(__file__).parent
            / "fixtures"
            / "student_numbers"
            / "full"
        )

    def assert_student_number_text(
        self,
        filename,
        expected_digits,
    ):
        text = find_student_number_text(
            self.fixture_dir / filename
        )

        self.assertIsNotNone(text)

        normalized = text.lower()

        self.assertTrue(
            "student number" in normalized
            or "studentenommer" in normalized
        )

        digits = re.sub(
            r"\D",
            "",
            text,
        )

        self.assertEqual(
            digits,
            expected_digits,
        )

    def test_finds_first_student_number_text(self):
        self.assert_student_number_text(
            "student_37279432_a.jpeg",
            "37279432",
        )

    def test_finds_second_student_number_text(self):
        self.assert_student_number_text(
            "student_37471899.jpeg",
            "37471899",
        )

    def test_finds_third_student_number_text(self):
        self.assert_student_number_text(
            "student_37279432_b.jpeg",
            "37279432",
        )

    def test_finds_fourth_student_number_text(self):
        self.assert_student_number_text(
            "student_35226455.jpeg",
            "35224455",
        )