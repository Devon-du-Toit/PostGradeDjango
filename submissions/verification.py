from django.core.exceptions import ValidationError

from submissions.models import Submission


def verify_submission(submission, enrollment, actor=None):
    if submission.status == Submission.Status.MARKED:
        raise ValidationError(
            "A marked submission cannot be re-verified."
        )

    if enrollment.course_id != submission.assessment.course_id:
        raise ValidationError(
            "Enrollment does not belong to the submission's course."
        )

    # An illegal transition is the caller's mistake, so it is reported
    # like the checks above (400) instead of escaping as a server error.
    try:
        submission.record_status_change(
            actor=actor,
            new_status=Submission.Status.VERIFIED,
            reason="Verified against enrollment",
            new_enrollment=enrollment,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    return submission
