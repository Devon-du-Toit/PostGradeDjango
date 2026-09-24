from dataclasses import dataclass

# Give every OCR/document model a common output shape
@dataclass(frozen=True)
class StudentNumberCandidate:
    value: str
    confidence: float | None = None


@dataclass(frozen=True)
class StudentNumberRegion:
    text: str
    confidence: float | None
    box: tuple[int, int, int, int]
    image_width: int
    image_height: int