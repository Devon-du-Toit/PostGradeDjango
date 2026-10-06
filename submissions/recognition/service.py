import logging
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings
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

MAX_ERROR_LENGTH = 2000

REASON_AREA_NOT_FOUND = "Student number area could not be identified"
REASON_NOT_MATCHED = "Student number could not be matched"

logger = logging.getLogger(__name__)


@contextmanager
def _local_file_path(field_file):
    """Yield a local filesystem path for a submission file.

    OCR needs a real path. Local storage already has one; storage without
    local paths (e.g. cloud blob storage) is copied to a temporary file
    through the Storage API and removed afterwards.
    """
    try:
        local_path = field_file.path
    except NotImplementedError:
        local_path = None

    if local_path is not None:
        yield Path(local_path)
        return

    field_file.open("rb")
    try:
        raw_bytes = field_file.read()
    finally:
        field_file.close()

    with NamedTemporaryFile(
        suffix=Path(field_file.name).suffix,
        delete=False,
    ) as temporary_file:
        temporary_file.write(raw_bytes)
        temporary_path = Path(temporary_file.name)

    try:
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def recognize_submission(submission, *, job_id=None, claimed_attempt=None):
    if submission.qr_group_key:
        return recognize_group(
            submission, job_id=job_id, claimed_attempt=claimed_attempt
        )
    return recognize_single_submission(submission)


def recognize_single_submission(submission, *, attempt=None):
    method = submission.recognition_method
    if method not in ("ocr", "bubble"):
        raise ValueError("Unsupported recognition method")
    attempt = attempt or RecognitionAttempt(
        submission=submission,
        method=method,
        processing_version="bubble-1" if method == "bubble" else PROCESSING_VERSION,
    )

    try:
        result = run_recognition(submission, attempt)
    except Exception as exc:
        attempt.outcome = RecognitionAttempt.Outcome.ERROR
        attempt.error_type = type(exc).__name__
        attempt.error_message = str(exc)[:MAX_ERROR_LENGTH]
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
    if submission.recognition_method == "bubble":
        return run_bubble_recognition(submission, attempt)
    # Determine which student this uploaded script belongs to.
    with (
        _local_file_path(submission.file) as local_path,
        recognition_image(local_path) as image_path,
    ):

        # Check image quality before trying OCR.
        quality_result = assess_image_quality(image_path)

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

    candidates = extract_student_number_candidate(region.text)

    if not candidates:
        attempt.outcome = RecognitionAttempt.Outcome.NO_CANDIDATE
        return RecognitionResult(
            enrollment=None,
            reason=REASON_NOT_MATCHED,
        )

    attempt.raw_candidate = candidates[0].value
    attempt.raw_candidates = [
        {
            "value": candidate.value,
            "confidence": candidate.confidence,
        }
        for candidate in candidates
    ]

    enrollments = submission.assessment.course.enrollments.select_related("student")

    enrollment_by_number = {
        enrollment.student.student_number: enrollment for enrollment in enrollments
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


def run_bubble_recognition(submission, attempt):
    # Lazy worker-only import. Selecting bubbles never invokes PaddleOCR,
    # text localization or fuzzy number matching.
    from submissions.recognition.bubbles import read_bubbles

    with (
        _local_file_path(submission.file) as local_path,
        recognition_image(local_path) as image_path,
    ):
        reading = read_bubbles(image_path)
    if reading.region is None:
        attempt.outcome = RecognitionAttempt.Outcome.REGION_NOT_FOUND
        attempt.quality_issues = [reading.reason]
        return RecognitionResult(enrollment=None, reason=reading.reason)
    attempt.region = reading.region
    attempt.template_version = reading.template
    attempt.column_scores = reading.columns
    attempt.column_ambiguity = reading.ambiguity
    attempt.raw_candidate = reading.candidate
    attempt.confidence = reading.confidence
    attempt.confidence_type = RecognitionAttempt.ConfidenceType.BUBBLE_MARGIN
    attempt.region_image.save(
        f"submission_{submission.pk}_bubble.png",
        ContentFile(reading.image),
        save=False,
    )
    if reading.ambiguity:
        attempt.outcome = RecognitionAttempt.Outcome.NO_CANDIDATE
        return RecognitionResult(enrollment=None, reason=reading.reason)
    attempt.raw_candidates = [
        {"value": reading.candidate, "confidence": reading.confidence}
    ]
    # Exact equality only; no OCR, nearest-number lookup or fuzzy matching.
    enrollment = (
        submission.assessment.course.enrollments.select_related("student")
        .filter(
            student__student_number=reading.candidate,
        )
        .first()
    )
    if enrollment is None or not getattr(settings, "BUBBLE_AUTO_MATCH_ENABLED", True):
        attempt.outcome = RecognitionAttempt.Outcome.NO_MATCH
        return RecognitionResult(enrollment=None, reason=REASON_NOT_MATCHED)
    attempt.outcome = RecognitionAttempt.Outcome.MATCHED
    attempt.suggested_enrollment = enrollment
    attempt.suggested_student_number = reading.candidate
    return RecognitionResult(enrollment=enrollment, reason=None)


def recognize_group(submission, *, job_id=None, claimed_attempt=None):
    from copy import copy

    from django.db import transaction

    from submissions.models import RecognitionJob, ScriptPage, Submission
    from submissions.qr import group_issues, ordered_pages

    version = submission.version
    evidence = []
    for page in ordered_pages(submission):
        per_page = copy(submission)
        per_page.file = page.file
        attempt = RecognitionAttempt(
            submission=submission,
            method=submission.recognition_method,
            processing_version=(
                "bubble-1"
                if submission.recognition_method == "bubble"
                else PROCESSING_VERSION
            ),
        )
        try:
            result = recognize_single_submission(per_page, attempt=attempt)
        except Exception:
            # Preserve the page/group even if recognition fails on this page.
            result = RecognitionResult(enrollment=None, reason="Recognition failed")
        evidence.append((page.pk, result.enrollment, attempt))
    with transaction.atomic():
        if job_id is not None:
            job = (
                RecognitionJob.objects.select_for_update()
                .filter(pk=job_id, submission_id=submission.pk)
                .first()
            )
            if (
                job is None
                or job.status != RecognitionJob.Status.RUNNING
                or job.attempts != claimed_attempt
            ):
                return RecognitionResult(
                    enrollment=None, reason="Obsolete group recognition lease"
                )
        current = Submission.objects.select_for_update().get(pk=submission.pk)
        if current.version != version or current.status != Submission.Status.PROCESSING:
            return RecognitionResult(
                enrollment=None, reason="Obsolete group recognition"
            )
        for page_id, enrollment, attempt in evidence:
            ScriptPage.objects.filter(pk=page_id).update(
                suggested_enrollment=enrollment,
                recognition_outcome=attempt.outcome if attempt else "error",
                quality_issues=(
                    attempt.quality_issues if attempt else ["Recognition failed"]
                ),
            )
        current.qr_review_issues = group_issues(current)
        current.save(update_fields=["qr_review_issues"])
        identities = {
            enrollment.pk: enrollment for _, enrollment, _ in evidence if enrollment
        }
        if current.qr_review_issues or len(identities) != 1:
            return RecognitionResult(
                enrollment=None, reason="QR group requires manual review"
            )
        return RecognitionResult(
            enrollment=next(iter(identities.values())), reason=None
        )
