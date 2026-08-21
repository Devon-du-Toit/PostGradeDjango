from dataclasses import dataclass

# Give every OCR/document model a common output shape
@dataclass(frozen=True)
class StudentNumberCandidate:
    value: str
    confidence: float | None = None