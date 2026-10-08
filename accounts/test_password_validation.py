from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase


class SpecialCharacterPasswordTests(SimpleTestCase):
    def test_rejects_missing_special_character_including_whitespace(self):
        for password in ("SyntheticPassword854", "Synthetic Password854 "):
            with self.subTest(password=password):
                with self.assertRaises(ValidationError) as error:
                    validate_password(password)
                self.assertIn(
                    "password_no_special_character",
                    [item.code for item in error.exception.error_list],
                )

    def test_accepts_password_with_special_character(self):
        validate_password("SyntheticPassword854!")
