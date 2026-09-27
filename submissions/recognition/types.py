from dataclasses import dataclass

# Give every OCR/document model a common output shape
@dataclass(frozen=True)
class StudentNumberCandidate:
    value: str
    confidence: float | None = None

@dataclass(frozen=True)
class ImageQualityResult:
    usable: bool
    reason: str | None = None
@dataclass(frozen=True)
class RecognitionResult:
    enrollment: object | None = None
    reason: str | None = None