import logging

from django.core.files.base import ContentFile
from submissions.models import RecognitionAttempt
from submissions.recognition.document import (
    crop_image,
    recognition_image,
)
from submissions.recognition.localization import (
    locate_student_number,
)
from submissions.recognition.matching import (
    find_best_student_number_match,
)
from submissions.recognition.paddleocr import (
    extract_student_number_candidate,
)
from submissions.recognition.quality import (
    assess_image_quality,
)
from submissions.recognition.types import (
    RecognitionResult,
)

PROCESSING_VERSION = "ocr-1"

REASON_AREA_NOT_FOUND = "Student number area could not be identified"
REASON_NOT_MATCHED = "Student number could not be matched"

logger = logging.getLogger(__name__)

def recognize_submission(submission):
    attempt = RecognitionAttempt(
        submission=submission,
        method=RecognitionAttempt.Method.OCR,
        processing_version=PROCESSING_VERSION,
    )

    try:
        result = run_recognition(submission, attempt)
    except Exception:
        attempt.outcome = RecognitionAttempt.Outcome.ERROR
        attempt.save()
        raise

    attempt.save()

    return result

def save_region_image(attempt, image_path, box):
    try:
        attempt.region_image.save(
            f"submission_{attempt.submission_id}.png",
            ContentFile(crop_image(image_path, box)),
            save=False,
        )
    except Exception:
        logger.warning(
            "Could not save recognition region image for submission %s",
            attempt.submission_id,
            exc_info=True,
        )

def run_recognition(submission, attempt):
    # Determine which student this uploaded script belongs to.
    with recognition_image(
        submission.file.path
    ) as image_path:

        # Check image quality before trying OCR.
        quality_result = assess_image_quality(
            image_path
        )

        if not quality_result.usable:
            attempt.outcome = RecognitionAttempt.Outcome.IMAGE_UNUSABLE
            attempt.quality_issues = [quality_result.reason]
            return RecognitionResult(
                enrollment=None,
                reason=quality_result.reason,
            )

        region = locate_student_number(image_path)

        if region is not None:
            save_region_image(attempt, image_path, region.box)

    if region is None:
        attempt.outcome = RecognitionAttempt.Outcome.REGION_NOT_FOUND
        return RecognitionResult(
            enrollment=None,
            reason=REASON_AREA_NOT_FOUND,
        )

    x1, y1, x2, y2 = region.box

    attempt.raw_text = region.text
    attempt.confidence = region.confidence
    attempt.confidence_type = RecognitionAttempt.ConfidenceType.OCR_SCORE
    attempt.region = {
        "page": 0,
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
        "image_width": region.image_width,
        "image_height": region.image_height,
    }

    candidates = extract_student_number_candidate(
        region.text
    )

    if not candidates:
        attempt.outcome = RecognitionAttempt.Outcome.NO_CANDIDATE
        return RecognitionResult(
            enrollment=None,
            reason=REASON_NOT_MATCHED,
        )

    attempt.raw_candidate = candidates[0].value

    enrollments = (
        submission.assessment.course
        .enrollments
        .select_related("student")
    )

    enrollment_by_number = {
        enrollment.student.student_number: enrollment
        for enrollment in enrollments
    }

    matched_number = find_best_student_number_match(
        candidates=candidates,
        valid_student_numbers=enrollment_by_number.keys(),
    )

    if matched_number is None:
        attempt.outcome = RecognitionAttempt.Outcome.NO_MATCH
        return RecognitionResult(
            enrollment=None,
            reason=REASON_NOT_MATCHED,
        )

    enrollment = enrollment_by_number[matched_number]

    attempt.outcome = RecognitionAttempt.Outcome.MATCHED
    attempt.suggested_enrollment = enrollment
    attempt.suggested_student_number = matched_number

    return RecognitionResult(
        enrollment=enrollment,
        reason=None,
    )
