from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from PIL import Image

from submissions.recognition.bubbles import read_bubbles
from submissions.tests.bubble_helpers import bubble_image, distorted_image


class BubbleRecognitionTests(SimpleTestCase):
    def read(self, image):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.png"
            image.save(path)
            return read_bubbles(path)

    def test_decodes_fills_not_written_digits_and_preserves_zeroes(self):
        reading = self.read(bubble_image("00123456", written="98765432"))
        self.assertEqual(reading.candidate, "00123456")
        self.assertEqual(reading.ambiguity, [])
        self.assertEqual(len(reading.columns), 8)
        self.assertEqual(len(reading.columns[0]["scores"]), 10)
        self.assertEqual(reading.region["page"], 0)
        self.assertEqual(len(reading.region["corners"]), 4)
        self.assertTrue(reading.image.startswith(b"\x89PNG"))

    def test_all_zeroes_are_not_cancelled_by_baseline(self):
        self.assertEqual(self.read(bubble_image("00000000")).candidate, "00000000")

    def test_versioned_compact_layout(self):
        reading = self.read(bubble_image(compact=True))
        self.assertEqual(reading.candidate, "01234567")
        self.assertEqual(reading.template, "nwu-eight-compact-1")

    def test_rotation_scale_skew_perspective_and_shadows(self):
        for options in (
            {"angle": 90},
            {"angle": 180},
            {"angle": 270},
            {"angle": 7},
            {"perspective": True},
            {"shadow": True},
            {"scale": 0.75},
        ):
            with self.subTest(options=options):
                reading = self.read(distorted_image(bubble_image(), **options))
                self.assertEqual(reading.candidate, "01234567")

    def test_blank_columns_are_explicit(self):
        marks = {column: [column] for column in range(8)}
        marks[2] = []
        reading = self.read(bubble_image(fills=marks))
        self.assertEqual(reading.candidate, "01X34567")
        self.assertIn({"column": 3, "reason": "empty"}, reading.ambiguity)

    def test_multiple_fills_are_never_resolved_from_handwriting(self):
        marks = {column: [column] for column in range(8)}
        marks[2] = [2, 5]
        reading = self.read(bubble_image(fills=marks))
        self.assertEqual(reading.candidate, "01X34567")
        self.assertIn({"column": 3, "reason": "multiple"}, reading.ambiguity)

    def test_faint_marks_and_erasures_do_not_silently_choose_digits(self):
        reading = self.read(bubble_image(shade=205))
        self.assertTrue(reading.ambiguity)
        self.assertTrue(all(column["digit"] is None for column in reading.columns))
        marks = {column: [column] for column in range(8)}
        marks[0] = [0, 8]
        reading = self.read(bubble_image(fills=marks, shade=160))
        self.assertIn("X", reading.candidate)

    def test_missing_marker_does_not_use_qr_or_text_as_a_grid(self):
        reading = self.read(bubble_image(missing_marker=True))
        self.assertIsNone(reading.region)
        self.assertEqual(reading.candidate, "")

    def test_two_plausible_grids_require_manual_review(self):
        first = bubble_image()
        second = bubble_image("87654321").crop((480, 130, 840, 700))
        image = Image.new("RGB", (1500, 1200), "white")
        image.paste(first, (0, 0))
        image.paste(second, (900, 130))
        self.assertIsNone(self.read(image).region)
