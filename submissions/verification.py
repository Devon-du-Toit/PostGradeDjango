from django.core.exceptions import ValidationError

from submissions.models import Submission


def verify_submission(submission, enrollment):
    if submission.status == Submission.Status.MARKED:
        raise ValidationError(
            "A marked submission cannot be re-verified."
        )

    if enrollment.course_id != submission.assessment.course_id:
        raise ValidationError(
            "Enrollment does not belong to the submission's course."
        )

    submission.enrollment = enrollment
    submission.status = Submission.Status.VERIFIED

    submission.save(
        update_fields=[
            "enrollment",
            "status",
            "updated_at",
        ]
    )

    return submission