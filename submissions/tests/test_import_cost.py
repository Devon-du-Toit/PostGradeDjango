import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class WebStartupImportTests(SimpleTestCase):
    """Web processes must not load the OCR engine (see get_ocr).

    Checked in a fresh interpreter: in the test run itself, other tests
    load PaddleOCR, so sys.modules here proves nothing.
    """

    def test_loading_the_urls_does_not_import_paddleocr(self):
        code = (
            "import sys, django; django.setup(); import config.urls; "
            "print('paddleocr' in sys.modules)"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=settings.BASE_DIR,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings"},
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")
