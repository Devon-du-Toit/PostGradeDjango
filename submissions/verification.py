from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from distribution.services import supersede_submission_emails
from submissions.models import Submission
from submissions.lifecycle import lock_submission_scope


def verify_submission(submission, enrollment, actor=None):
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
                reason="Verified against enrollment",
                new_enrollment=enrollment,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        supersede_submission_emails(locked)
    submission.refresh_from_db()
    return submission
