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


def recognize_submission(submission):
    with recognition_image(
        submission.file.path
    ) as image_path:
        student_number_text = (
            find_student_number_text(
                image_path
            )
        )

    if student_number_text is None:
        return None

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
        return None

    return enrollment_by_number[matched_number]