from submissions.recognition.document import (
    recognition_image,
)
from submissions.recognition.localization import (
    find_student_number_text,
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


def recognize_submission(submission):
    # Determine which student this uploaded script belongs to.
    with recognition_image(
        submission.file.path
    ) as image_path:

        # Check image quality before trying OCR.
        quality_result = assess_image_quality(
            image_path
        )

        if not quality_result.usable:
            return RecognitionResult(
                enrollment=None,
                reason=quality_result.reason,
            )

        student_number_text = (
            find_student_number_text(
                image_path
            )
        )

    if student_number_text is None:
        return RecognitionResult(
            enrollment=None,
            reason=(
                "Student number area could not be identified"
            ),
        )

    candidates = extract_student_number_candidate(
        student_number_text,
    )

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
        return RecognitionResult(
            enrollment=None,
            reason=(
                "Student number could not be matched"
            ),
        )

    return RecognitionResult(
        enrollment=enrollment_by_number[matched_number],
        reason=None,
    )