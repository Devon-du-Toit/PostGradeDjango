from pathlib import Path

from django.test import SimpleTestCase

from submissions.recognition.paddleocr import (
    PaddleOCRStudentNumberRecognitionProvider,
)


class PaddleOCRProviderTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.provider = (
            PaddleOCRStudentNumberRecognitionProvider()
        )

        cls.fixture_dir = (
            Path(__file__).parent
            / "fixtures"
            / "student_numbers"
            / "cropped"
        )

    def test_recognizes_first_student_number(self):
        candidates = self.provider.recognize(
            self.fixture_dir
            / "student_37279432_a.jpeg"
        )

        print("37279432_a:", candidates)

        self.assertTrue(candidates)

    def test_recognizes_second_student_number(self):
        candidates = self.provider.recognize(
            self.fixture_dir
            / "student_37471899.jpeg"
        )

        print("37471899:", candidates)

        self.assertTrue(candidates)

    def test_recognizes_third_student_number(self):
        candidates = self.provider.recognize(
            self.fixture_dir
            / "student_37279432_b.jpeg"
        )

        print("37279432_b:", candidates)

        self.assertTrue(candidates)

    def test_recognizes_fourth_student_number(self):
        candidates = self.provider.recognize(
            self.fixture_dir
            / "student_35226455.jpeg"
        )

        print("35226455:", candidates)

        self.assertTrue(candidates)