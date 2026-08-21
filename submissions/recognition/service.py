from submissions.recognition.matching import (
    find_best_student_number_match,
)


def recognize_submission(
    submission,
    provider,
):
    candidates = provider.recognize(
        submission.file.path,
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