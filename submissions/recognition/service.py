from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

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


@contextmanager
def _staged_local_file(field_file):
    """
    Materialize a submission's file as a local temporary file,
    regardless of what storage backend it actually lives on.
    Reads via field_file.open()/.read() - the Storage API -
    instead of submission.file.path, so this keeps working when
    the storage backend isn't local disk (e.g. S3).
    """
    suffix = Path(field_file.name).suffix

    field_file.open("rb")
    try:
        raw_bytes = field_file.read()
    finally:
        field_file.close()

    with NamedTemporaryFile(
        suffix=suffix,
        delete=False,
    ) as temporary_file:
        temporary_file.write(raw_bytes)
        temporary_path = Path(temporary_file.name)

    try:
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def recognize_submission(submission):
    with _staged_local_file(submission.file) as local_path:
        with recognition_image(
            local_path
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