"""Retain script evidence while changing current availability."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from distribution.services import supersede_submission_emails
from submissions.models import (
    RecognitionJob,
    Submission,
    SubmissionAudit,
    SubmissionFileRevision,
)


def retain_file_revision(submission, *, verification=False):
    if not submission.file:
        return
    existing = submission.file_revisions.filter(file=submission.file.name)
    if (
        existing.filter(version=submission.version).exists()
        if verification
        else existing.exists()
    ):
        return
    identity = {}
    if submission.enrollment_id:
        student = submission.enrollment.student
        identity = dict(
            student_number=student.student_number,
            first_name=student.first_name,
            last_name=student.last_name,
        )
        audit = (
            submission.audit_entries.filter(
                new_status="verified", new_enrollment_id=submission.enrollment_id
            )
            .order_by("-timestamp", "-pk")
            .first()
        )
        if audit and audit.new_identity.get("student_number"):
            identity["student_number"] = audit.new_identity["student_number"]
    SubmissionFileRevision.objects.create(
        submission=submission,
        file=submission.file.name,
        version=submission.version,
        original_filename=submission.original_filename,
        student_identity=identity,
        status=submission.status,
    )


def lock_submission_work(ids):
    ids = sorted(ids)
    list(
        RecognitionJob.objects.filter(
            submission_id__in=ids, status__in=RecognitionJob.ACTIVE_STATUSES
        )
        .order_by("pk")
        .select_for_update()
    )
    return list(
        Submission.objects.filter(pk__in=ids)
        .order_by("pk")
        .select_for_update(of=("self",))
    )


def record_retention(submission, actor, reason):
    submission.version += 1
    submission.save(
        update_fields=[
            "version",
            "archived_at",
            "superseded_at",
            "superseded_by",
            "updated_at",
        ]
    )
    SubmissionAudit.objects.create(
        submission=submission,
        actor=actor,
        previous_status=submission.status,
        new_status=submission.status,
        previous_enrollment=submission.enrollment,
        new_enrollment=submission.enrollment,
        reason=reason,
    )
    supersede_submission_emails(submission)
    from submissions.jobs import cancel_active_jobs

    cancel_active_jobs(submission)
    if submission.status == Submission.Status.PROCESSING:
        submission.record_status_change(
            actor,
            Submission.Status.NEEDS_VERIFICATION,
            reason="Processing stopped: " + reason,
        )


def archive_submission(submission, actor, version, reason):
    from submissions.lifecycle import lock_active_assessment

    with transaction.atomic():
        lock_active_assessment(submission.assessment_id)
        current = lock_submission_work([submission.pk])[0]
        if current.version != version or not reason.strip():
            raise ValidationError("Archive requires the current version and a reason.")
        if current.archived_at is None:
            retain_file_revision(current)
            current.archived_at = timezone.now()
            record_retention(current, actor, "Script archived: " + reason.strip())
        return current
