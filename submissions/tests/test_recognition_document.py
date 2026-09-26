from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf
from django.test import SimpleTestCase
from PIL import Image

from submissions.recognition.document import (
    recognition_image,
)


class RecognitionDocumentTests(SimpleTestCase):
    def test_image_is_returned_unchanged(self):# Test1: Does an image stay unchanged?
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

        # Test 3: Reject a PDF that contains no pages
        # added by Okuhle
    def test_empty_pdf_is_rejected(self):
        with NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as temporary_pdf:
            pdf_path = Path(
             temporary_pdf.name
        )
        #replaced this
        #with self.assertRaises(ValueError):
           # with recognition_image(pdf_path):
            #    pass
        # with this
        with self.assertRaisesRegex(
            ValueError,
            "PDF is empty",
):
            with recognition_image(pdf_path):
              pass

        pdf_path.unlink(
            missing_ok=True
    )
     # Test 4: Reject a corrupt PDF
    def test_corrupt_pdf_is_rejected(self):
        with NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as temporary_pdf:
            temporary_pdf.write(
                b"This is not a valid PDF file"
        )
        pdf_path = Path(
            temporary_pdf.name
        )

        with self.assertRaisesRegex(
             ValueError,
                "PDF is corrupt or invalid",
        ):
            with recognition_image(pdf_path):
                pass

        pdf_path.unlink(
            missing_ok=True
        ) 

        # Test 5: Reject an encrypted PDF
    def test_encrypted_pdf_is_rejected(self):
        with NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
        ) as temporary_pdf:
            pdf_path = Path(
                temporary_pdf.name
            )

        document = pymupdf.open()
        document.new_page()

        document.save(
            pdf_path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
        document.close()

        with self.assertRaisesRegex(
        ValueError,
        "PDF is encrypted",
        ):
            with recognition_image(pdf_path):
                pass

        pdf_path.unlink(
            missing_ok=True
        ) 
        def test_multipage_pdf_uses_first_page_only(self):
            with NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
            ) as temporary_pdf:
                pdf_path = Path(
                    temporary_pdf.name
                )

            document = pymupdf.open()

            first_page = document.new_page()
            first_page.insert_text(
                (72, 72),
                "FIRST PAGE",
            )

            second_page = document.new_page()
            second_page.insert_text(
                (72, 72),
                "SECOND PAGE",
            )

            document.save(
                pdf_path
            )
            document.close()

            try:
                with recognition_image(
                    pdf_path
                ) as image_path:
                    rendered_image = pymupdf.open(
                        image_path
                    )

                    self.assertEqual(
                        rendered_image.page_count,
                        1,
                    )

                    rendered_image.close()

                original_document = pymupdf.open(
                    pdf_path
                )

                self.assertEqual(
                    original_document.page_count,
                    2,
                )

                original_document.close()

            finally:
                pdf_path.unlink(
                    missing_ok=True
                ) 