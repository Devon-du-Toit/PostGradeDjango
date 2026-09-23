from pathlib import Path

import cv2
from django.test import SimpleTestCase

from submissions.recognition.quality import (
    assess_image_quality,
    calculate_blur_score,
    calculate_brightness,
    calculate_contrast,
    get_image_resolution,
)


class RecognitionQualityTests(SimpleTestCase):
    def test_blurred_image_has_lower_blur_score(self):
        original_path = Path(
            "submissions/tests/fixtures/"
            "student_numbers/full/"
            "student_35226455.jpeg"
        )

        original = cv2.imread(
            str(original_path)
        )

        blurred = cv2.GaussianBlur(
            original,
            (7, 7),
            0,
        )

        temporary_path = Path(
            "temp_test_blurred.jpeg"
        )

        cv2.imwrite(
            str(temporary_path),
            blurred,
        )

        try:
            original_score = calculate_blur_score(
                original_path
            )
            blurred_score = calculate_blur_score(
                temporary_path
            )

            self.assertLess(
                blurred_score,
                original_score,
            )
        finally:
            temporary_path.unlink(
                missing_ok=True
            )

    def test_image_resolution_is_returned(self):
        image_path = Path(
            "submissions/tests/fixtures/"
            "student_numbers/full/"
            "student_35226455.jpeg"
        )

        width, height = get_image_resolution(
            image_path
        )

        self.assertEqual(
            width,
            1600,
        )
        self.assertEqual(
            height,
            1014,
        )

    def test_brightness_is_calculated(self):
        image_path = Path(
            "submissions/tests/fixtures/"
            "student_numbers/full/"
            "student_35226455.jpeg"
        )

        brightness = calculate_brightness(
            image_path
        )

        self.assertGreater(
            brightness,
            0,
        )
        self.assertLessEqual(
            brightness,
            255,
        )

    def test_contrast_is_calculated(self):
        image_path = Path(
            "submissions/tests/fixtures/"
            "student_numbers/full/"
            "student_35226455.jpeg"
        )

        contrast = calculate_contrast(
            image_path
        )

        self.assertGreater(
            contrast,
            0,
        )
        def test_good_scan_is_usable(self):
            image_path = Path(
                "submissions/tests/fixtures/"
                "student_numbers/full/"
                "student_35226455.jpeg"
            )

            result = assess_image_quality(
                image_path
            )

            self.assertTrue(
                result.usable
            )
            self.assertIsNone(
                result.reason
            )

    def test_low_resolution_scan_is_not_usable(self):
        original_path = Path(
            "submissions/tests/fixtures/"
            "student_numbers/full/"
            "student_35226455.jpeg"
        )

        original = cv2.imread(
            str(original_path)
        )

        low_resolution = cv2.resize(
            original,
            (400, 254),
        )

        temporary_path = Path(
            "temp_test_low_resolution.jpeg"
        )

        cv2.imwrite(
            str(temporary_path),
            low_resolution,
        )

        try:
            result = assess_image_quality(
                temporary_path
            )

            self.assertFalse(
                result.usable
            )
            self.assertEqual(
                result.reason,
                "Image resolution is too low",
            )
        finally:
            temporary_path.unlink(
                missing_ok=True
            )