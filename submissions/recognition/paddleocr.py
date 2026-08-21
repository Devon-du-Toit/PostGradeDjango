import re

from submissions.recognition.types import (
    StudentNumberCandidate,
)


def extract_student_number_candidate(text):
    digits = re.sub(
        r"\D",
        "",
        text,
    )

    if not digits:
        return []

    return [
        StudentNumberCandidate(
            value=digits,
            confidence=None,
        )
    ]