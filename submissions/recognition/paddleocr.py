import re

from paddleocr import TextRecognition
from submissions.recognition.types import (
    StudentNumberCandidate,
)


class PaddleOCRStudentNumberRecognitionProvider:
    MODEL_NAME = "PP-OCRv5_server_rec"

    def __init__(self):
        self.model = TextRecognition(
            model_name=self.MODEL_NAME,
        )

    def recognize(self, image_path):
        results = self.model.predict(
            input=str(image_path),
            batch_size=1,
        )

        candidates = []

        for result in results:
            data = result.json

            text = data["res"]["rec_text"]
            score = data["res"]["rec_score"]

            digits = re.sub(
                r"\D",
                "",
                text,
            )

            if not digits:
                continue

            candidates.append(
                StudentNumberCandidate(
                    value=digits,
                    confidence=float(score),
                )
            )

        return candidates