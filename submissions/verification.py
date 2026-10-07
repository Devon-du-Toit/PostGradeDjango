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
        from django.utils import timezone

        from students.models import Enrollment
        from submissions.retention import lock_submission_work, record_retention

        contenders = Submission.objects.filter(
            assessment_id=submission.assessment_id,
            enrollment=enrollment,
            status="verified",
            archived_at__isnull=True,
            superseded_at__isnull=True,
        )
        locked_rows = lock_submission_work(
            set(contenders.values_list("pk", flat=True)) | {submission.pk}
        )
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
        enrollment = get_object_or_404(
            Enrollment.objects.active()
            .select_related("student")
            .select_for_update(of=("self",)),
            pk=enrollment.pk,
            course_id=locked.assessment.course_id,
        )
        if locked.qr_group_key:
            from submissions.qr import group_issues

            issues = group_issues(locked)
            if issues:
                raise ValidationError(
                    "Resolve QR page review before verifying: " + ", ".join(issues)
                )
            suggestions = set(
                locked.pages.filter(excluded=False)
                .exclude(suggested_enrollment=None)
                .values_list("suggested_enrollment_id", flat=True)
            )
            if suggestions and enrollment.pk not in suggestions and not reason.strip():
                raise ValidationError(
                    "A conflicting student requires an explicit review reason."
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
        for previous in locked_rows:
            if (
                previous.pk != locked.pk
                and previous.status == Submission.Status.VERIFIED
                and previous.enrollment_id == enrollment.pk
                and previous.archived_at is None
                and previous.superseded_at is None
            ):
                if (previous.created_at, previous.pk) > (locked.created_at, locked.pk):
                    raise ValidationError(
                        "A newer verified script is active for this student. Archive the older upload or review the newer script."
                    )
                previous.superseded_at, previous.superseded_by = timezone.now(), locked
                record_retention(previous, actor, "Replaced by newer verified script")
        try:
            locked.record_status_change(
                actor=actor,
                new_status=Submission.Status.VERIFIED,
                reason=reason.strip() or "Verified against enrollment",
                new_enrollment=enrollment,
                expected_version=expected_version,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if locked.qr_group_key:
            locked.pages.filter(excluded=False).update(
                linked_enrollment=locked.enrollment
            )
        from submissions.retention import retain_file_revision

        retain_file_revision(locked, verification=True)
        supersede_submission_emails(locked)
    submission.refresh_from_db()
    return submission
