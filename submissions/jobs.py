import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from students.models import Enrollment
from submissions.models import RecognitionJob, Submission
from submissions.recognition.service import recognize_submission

logger = logging.getLogger(__name__)

LEASE_DURATION = timedelta(minutes=5)

RETRY_DELAYS = [
    timedelta(seconds=30),
    timedelta(minutes=2),
]

MAX_ERROR_LENGTH = 2000

RETRYABLE_STATUSES = [
    Submission.Status.RECOGNITION_FAILED,
    Submission.Status.NEEDS_VERIFICATION,
]


def enqueue_recognition(submission):
    if not Submission.objects.active().filter(pk=submission.pk).exists():
        raise ValidationError("Archived submissions cannot be processed.")
    active_job = submission.recognition_jobs.filter(
        status__in=RecognitionJob.ACTIVE_STATUSES,
    ).first()

    if active_job is not None:
        return active_job

    try:
        # Savepoint: a lost race only rolls back this insert.
        with transaction.atomic():
            return RecognitionJob.objects.create(
                submission=submission,
            )
    except IntegrityError:
        return submission.recognition_jobs.get(
            status__in=RecognitionJob.ACTIVE_STATUSES,
        )


def cancel_active_jobs(submission):
    # A running job's worker sees "cancelled" when it finishes and discards its result.
    now = timezone.now()

    return submission.recognition_jobs.filter(
        status__in=RecognitionJob.ACTIVE_STATUSES,
    ).update(
        status=RecognitionJob.Status.CANCELLED,
        lease_expires_at=None,
        finished_at=now,
        updated_at=now,
    )


def claim_next_job():
    now = timezone.now()

    with transaction.atomic():
        job = (
            RecognitionJob.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                status=RecognitionJob.Status.QUEUED,
                run_after__lte=now,
                submission__assessment__archived_at__isnull=True,
                submission__assessment__course__archived_at__isnull=True,
            )
            .order_by("run_after")
            .first()
        )

        if job is None:
            return None

        job.status = RecognitionJob.Status.RUNNING
        job.attempts += 1
        job.started_at = now
        job.lease_expires_at = now + LEASE_DURATION

        job.save(
            update_fields=[
                "status",
                "attempts",
                "started_at",
                "lease_expires_at",
                "updated_at",
            ]
        )

    return job


def run_job(job, claimed_attempt):
    if not Submission.objects.active().filter(pk=job.submission_id).exists():
        cancel_active_jobs(job.submission)
        return
    try:
        result = recognize_submission(
            job.submission,
        )
    except Exception as exc:
        logger.exception(
            "Recognition job %s failed on attempt %s",
            job.id,
            claimed_attempt,
        )
        fail_job(job.id, claimed_attempt, exc)
        return

    finish_job(job.id, claimed_attempt, result.enrollment)


def lock_current_job(job_id, claimed_attempt):
    # Returns the job only if this worker still owns it (fencing token).
    job = RecognitionJob.objects.select_for_update().get(
        pk=job_id,
    )

    if job.status != RecognitionJob.Status.RUNNING or job.attempts != claimed_attempt:
        return None

    return job


def finish_job(job_id, claimed_attempt, enrollment):
    now = timezone.now()

    with transaction.atomic():
        job = lock_current_job(job_id, claimed_attempt)

        if job is None:
            return

        job.status = RecognitionJob.Status.SUCCEEDED
        job.finished_at = now
        job.lease_expires_at = None

        job.save(
            update_fields=[
                "status",
                "finished_at",
                "lease_expires_at",
                "updated_at",
            ]
        )

        # Only a submission still waiting on this job may be changed;
        # a verified or replaced submission keeps its current state.
        new_status = (
            Submission.Status.MATCHED
            if enrollment is not None
            else Submission.Status.NEEDS_VERIFICATION
        )
        _transition_processing(
            job,
            new_status,
            enrollment=enrollment,
            reason=(
                "Automatic recognition matched"
                if enrollment is not None
                else "Automatic recognition could not match"
            ),
        )


def _transition_processing(job, new_status, *, enrollment=None, reason):
    # The job lock is already held. Replacement also locks job before submission.
    submission = (
        Submission.objects.active()
        .select_related("assessment__course")
        .select_for_update(of=("self",))
        .filter(
            pk=job.submission_id,
            status=Submission.Status.PROCESSING,
        )
        .first()
    )
    if submission is not None:
        if enrollment is not None:
            # Lock submission before enrollment, matching deletion's FK-clear order.
            enrollment = (
                Enrollment.objects.select_related("student")
                .select_for_update(of=("self",))
                .filter(
                    pk=enrollment.pk,
                    course_id=submission.assessment.course_id,
                    student__owner_id=submission.assessment.course.owner_id,
                )
                .first()
            )
            if enrollment is None:
                new_status = Submission.Status.NEEDS_VERIFICATION
                reason = "Recognition suggestion is no longer a valid class enrollment"
        submission.record_status_change(
            actor=None,
            new_status=new_status,
            new_enrollment=enrollment,
            reason=reason,
        )


def retry_or_fail(job, error, delay, now):
    # Caller must hold the job's row lock.
    job.last_error = error[:MAX_ERROR_LENGTH]
    job.lease_expires_at = None

    if job.attempts < job.max_attempts:
        job.status = RecognitionJob.Status.QUEUED
        job.run_after = now + delay
    else:
        job.status = RecognitionJob.Status.FAILED
        job.finished_at = now

        _transition_processing(
            job,
            Submission.Status.RECOGNITION_FAILED,
            reason="Automatic recognition failed",
        )

    job.save(
        update_fields=[
            "status",
            "last_error",
            "lease_expires_at",
            "run_after",
            "finished_at",
            "updated_at",
        ]
    )


def fail_job(job_id, claimed_attempt, exc):
    now = timezone.now()

    with transaction.atomic():
        job = lock_current_job(job_id, claimed_attempt)

        if job is None:
            return

        delay = RETRY_DELAYS[min(job.attempts - 1, len(RETRY_DELAYS) - 1)]

        retry_or_fail(
            job,
            f"{type(exc).__name__}: {exc}",
            delay,
            now,
        )


def recover_expired_jobs():
    now = timezone.now()
    recovered = 0

    with transaction.atomic():
        expired_jobs = RecognitionJob.objects.select_for_update(
            skip_locked=True
        ).filter(
            status=RecognitionJob.Status.RUNNING,
            lease_expires_at__lt=now,
        )

        for job in expired_jobs:
            retry_or_fail(
                job,
                "Worker stopped before the job finished.",
                timedelta(0),
                now,
            )
            recovered += 1

    return recovered


def process_next_job():
    job = claim_next_job()

    if job is None:
        return False

    run_job(job, job.attempts)

    return True


def retry_recognition(submission_id, actor=None, expected_version=None):
    with transaction.atomic():
        from submissions.lifecycle import lock_submission_scope

        try:
            lock_submission_scope(submission_id)
        except Http404 as exc:
            raise ValidationError("Archived submissions cannot be retried.") from exc
        # Lock the submission so two retry clicks cannot both enqueue.
        submission = Submission.objects.select_for_update().get(
            pk=submission_id,
        )
        if not Submission.objects.active().filter(pk=submission_id).exists():
            raise ValidationError("Archived submissions cannot be retried.")

        if expected_version is not None and submission.version != expected_version:
            raise ValidationError("This submission has changed. Reload and try again.")

        # Already queued or running: a repeated retry is a no-op.
        if submission.status == Submission.Status.PROCESSING:
            return submission

        if submission.status not in RETRYABLE_STATUSES:
            raise ValidationError(
                "Only submissions whose recognition failed or needs "
                "verification can be retried."
            )

        submission.record_status_change(
            actor=actor,
            new_status=Submission.Status.PROCESSING,
            new_enrollment=None,
            reason="Recognition retried",
            expected_version=expected_version,
        )

        enqueue_recognition(submission)

    return submission
