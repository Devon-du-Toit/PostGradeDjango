from pathlib import Path

from paddleocr import PaddleOCR


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


def find_student_number_text(image_path):
    image_path = Path(image_path)

    ocr = get_ocr()

    results = ocr.predict(
        input=str(image_path),
    )

    for result in results:
        data = result.json["res"]

        texts = data["rec_texts"]

        for text in texts:
            normalized = text.lower()

            if (
                "student number" in normalized
                or "studentenommer" in normalized
            ):
                return text

    return None