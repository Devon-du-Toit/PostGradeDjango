from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from distribution.services import supersede_submission_emails
from submissions.lifecycle import lock_submission_scope
from submissions.models import Submission


def verify_submission(
    submission,
    enrollment,
    actor=None,
    *,
    expected_version=None,
    correction=False,
    reason="",
):
    with transaction.atomic():
        lock_submission_scope(submission.pk)
        locked = get_object_or_404(
            Submission.objects.active()
            .select_related("assessment__course")
            .select_for_update(of=("self",)),
            pk=submission.pk,
        )
        if enrollment.course_id != locked.assessment.course_id:
            raise ValidationError(
                "Enrollment does not belong to the submission's course."
            )
        if expected_version is not None and expected_version != locked.version:
            raise ValidationError("This submission has changed. Reload and try again.")
        if correction:
            if expected_version is None or not reason.strip():
                raise ValidationError("Corrections require a version and a reason.")
            if locked.status != Submission.Status.VERIFIED:
                raise ValidationError("Only verified submissions can be corrected.")
        elif (
            locked.status == Submission.Status.VERIFIED
            and locked.enrollment_id not in (None, enrollment.pk)
        ):
            raise ValidationError(
                "Use the correction endpoint with a version and reason to change a verified student."
            )
        # Repeating a confirmation must not create a new delivery version.
        if (
            locked.status == Submission.Status.VERIFIED
            and locked.enrollment_id == enrollment.pk
        ):
            submission.refresh_from_db()
            return submission
        try:
            locked.record_status_change(
                actor=actor,
                new_status=Submission.Status.VERIFIED,
                reason=reason.strip() if correction else "Verified against enrollment",
                new_enrollment=enrollment,
                expected_version=expected_version,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        supersede_submission_emails(locked)
    submission.refresh_from_db()
    return submission
