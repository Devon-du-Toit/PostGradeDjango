from pathlib import Path

from paddleocr import PaddleOCR
from PIL import Image

from submissions.recognition.types import (
    StudentNumberRegion,
)

_ocr = None


def get_ocr():
    global _ocr

    if _ocr is None:
        _ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    return _ocr


def locate_student_number(image_path):
    image_path = Path(image_path)

    ocr = get_ocr()

    results = ocr.predict(
        input=str(image_path),
    )

    for result in results:
        data = result.json["res"]

        for text, score, box in zip(
            data["rec_texts"],
            data["rec_scores"],
            data["rec_boxes"],
        ):
            normalized = text.lower()

            if (
                "student number" in normalized
                or "studentenommer" in normalized
            ):
                with Image.open(image_path) as image:
                    image_width, image_height = image.size

                return StudentNumberRegion(
                    text=text,
                    confidence=float(score),
                    box=tuple(int(value) for value in box),
                    image_width=image_width,
                    image_height=image_height,
                )

    return None


def find_student_number_text(image_path):
    region = locate_student_number(image_path)

    if region is None:
        return None

    return region.text