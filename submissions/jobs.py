import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from submissions.models import RecognitionJob, Submission
from submissions.recognition.service import recognize_submission


logger = logging.getLogger(__name__)

LEASE_DURATION = timedelta(minutes=5)

RETRY_DELAYS = [
    timedelta(seconds=30),
    timedelta(minutes=2),
]

MAX_ERROR_LENGTH = 2000


def enqueue_recognition(submission):
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


def claim_next_job():
    now = timezone.now()

    with transaction.atomic():
        job = (
            RecognitionJob.objects
            .select_for_update(skip_locked=True)
            .filter(
                status=RecognitionJob.Status.QUEUED,
                run_after__lte=now,
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
    try:
        enrollment = recognize_submission(
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

    finish_job(job.id, claimed_attempt, enrollment)


def lock_current_job(job_id, claimed_attempt):
    # Returns the job only if this worker still owns it (fencing token).
    job = RecognitionJob.objects.select_for_update().get(
        pk=job_id,
    )

    if (
        job.status != RecognitionJob.Status.RUNNING
        or job.attempts != claimed_attempt
    ):
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
        Submission.objects.filter(
            pk=job.submission_id,
            status=Submission.Status.PROCESSING,
        ).update(
            enrollment=enrollment,
            status=(
                Submission.Status.MATCHED
                if enrollment is not None
                else Submission.Status.NEEDS_VERIFICATION
            ),
            updated_at=now,
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

        Submission.objects.filter(
            pk=job.submission_id,
            status=Submission.Status.PROCESSING,
        ).update(
            status=Submission.Status.RECOGNITION_FAILED,
            updated_at=now,
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

        delay = RETRY_DELAYS[
            min(job.attempts - 1, len(RETRY_DELAYS) - 1)
        ]

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
        expired_jobs = (
            RecognitionJob.objects
            .select_for_update(skip_locked=True)
            .filter(
                status=RecognitionJob.Status.RUNNING,
                lease_expires_at__lt=now,
            )
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