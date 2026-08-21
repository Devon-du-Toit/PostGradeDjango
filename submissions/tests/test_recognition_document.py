from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf
from django.test import SimpleTestCase
from PIL import Image

from submissions.recognition.document import (
    recognition_image,
)


class RecognitionDocumentTests(SimpleTestCase):
    def test_image_is_returned_unchanged(self):
        image_path = Path(
            "example.jpeg"
        )

        with recognition_image(
                image_path
        ) as result:
            self.assertEqual(
                result,
                image_path,
            )

    def test_first_pdf_page_is_rendered_to_image(self):
        with NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
        ) as temporary_pdf:
            pdf_path = Path(
                temporary_pdf.name
            )

        document = pymupdf.open()
        page = document.new_page()

        page.insert_text(
            (72, 72),
            "Student number: 37279432",
        )

        document.save(
            pdf_path
        )
        document.close()

        with recognition_image(
                pdf_path
        ) as image_path:
            self.assertTrue(
                image_path.exists()
            )

            with Image.open(image_path) as image:
                self.assertGreater(
                    image.width,
                    0,
                )
                self.assertGreater(
                    image.height,
                    0,
                )

            temporary_image_path = image_path

        self.assertFalse(
            temporary_image_path.exists()
        )

        pdf_path.unlink(
            missing_ok=True
        )