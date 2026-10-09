"""Synthetic regressions for small printed QR codes; no student data."""

import cv2
import numpy as np
import pymupdf
from django.test import SimpleTestCase

from submissions.qr import decode_page


def vector_page(values):
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        for index, value in enumerate(values):
            code = cv2.QRCodeEncoder_create().encode(value)[2:-2, 2:-2]
            left, top, step = 72, 15 + index * 100, 1.7
            # Match printing artifacts: thin white seams between vector
            # modules and a horizontal rule touching the code's lower edge.
            for y, row in enumerate(code):
                for x, cell in enumerate(row):
                    if cell == 0:
                        page.draw_rect(
                            pymupdf.Rect(
                                left + x * step + 0.025,
                                top + y * step + 0.025,
                                left + (x + 1) * step - 0.025,
                                top + (y + 1) * step - 0.025,
                            ),
                            color=None,
                            fill=(0, 0, 0),
                        )
            bottom = top + len(code) * step
            page.draw_line((left, bottom), (595, bottom), width=0.5)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False)
        rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3
        )
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


class QRDecoderTests(SimpleTestCase):
    value = "CMPG211,20230509,OT4,P1,#1"

    def test_tiny_vector_code_touching_rule_and_rotation(self):
        image = vector_page([self.value])
        for turns in (0, 1, 2, 3):
            with self.subTest(turns=turns):
                fields, status = decode_page(
                    np.ascontiguousarray(np.rot90(image, turns))
                )
                self.assertEqual(status, "readable")
                self.assertEqual(fields["test"], "OT4")
                self.assertEqual(fields["page_label"], "P1")
                self.assertEqual(fields["test_number"], "#1")

    def test_conflicting_payloads_are_not_silently_grouped(self):
        fields, status = decode_page(vector_page([self.value, self.value[:-1] + "2"]))
        self.assertEqual((fields, status), ({}, "conflicting_qr"))

    def test_repeated_identical_payload_is_readable(self):
        fields, status = decode_page(vector_page([self.value, self.value]))
        self.assertEqual(status, "readable")
        self.assertEqual(fields["test_number"], "#1")

    def test_decoded_invalid_metadata_is_rejected(self):
        self.assertEqual(
            decode_page(vector_page([self.value.replace("20230509", "20230230")])),
            ({}, "invalid_qr"),
        )

    def test_blank_page_is_unreadable(self):
        self.assertEqual(decode_page(vector_page([])), ({}, "unreadable_qr"))
