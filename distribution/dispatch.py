import logging
from datetime import timedelta
from email.utils import parseaddr
from smtplib import SMTPRecipientsRefused

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from assessments.models import Result
from distribution.models import ResultEmail


logger = logging.getLogger(__name__)

# Covers one SMTP send (EMAIL_TIMEOUT) with a wide margin.
LEASE_DURATION = timedelta(minutes=2)

RETRY_DELAYS = [
    timedelta(minutes=1),
    timedelta(minutes=4),
]

MAX_ERROR_LENGTH = 2000


def message_id(email):
    # Stable per result version: retries of the same email share an ID,
    # so mail clients can recognise a repeat.
    domain = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].partition("@")[2]

    return f"<{email.idempotency_key}@{domain or 'postgrade.local'}>"


def claim_next_email():
    now = timezone.now()

    with transaction.atomic():
        email = (
            ResultEmail.objects
            .select_for_update(skip_locked=True)
            .filter(
                status=ResultEmail.Status.QUEUED,
                run_after__lte=now,
            )
            .order_by("run_after")
            .first()
        )

        if email is None:
            return None

        email.status = ResultEmail.Status.SENDING
        email.attempts += 1
        email.lease_expires_at = now + LEASE_DURATION

        email.save(
            update_fields=[
                "status",
                "attempts",
                "lease_expires_at",
                "updated_at",
            ]
        )

    return email


def lock_owned_email(email_id, claimed_attempt, statuses):
    # Returns the email only if this worker still owns it (fencing token).
    email = ResultEmail.objects.select_for_update().get(
        pk=email_id,
    )

    if (
        email.status not in statuses
        or email.attempts != claimed_attempt
    ):
        return None

    return email


def mark_sent(email_id, claimed_attempt):
    now = timezone.now()

    with transaction.atomic():
        # A slow send may already have been recovered as delivery_unknown;
        # the send did happen, so record it.
        email = lock_owned_email(
            email_id,
            claimed_attempt,
            [
                ResultEmail.Status.SENDING,
                ResultEmail.Status.FAILED,
            ],
        )

        if email is None:
            return

        if (
            email.status == ResultEmail.Status.FAILED
            and email.failure_reason
            != ResultEmail.FailureReason.DELIVERY_UNKNOWN
        ):
            return

        email.status = ResultEmail.Status.SENT
        email.failure_reason = ""
        email.sent_at = now
        email.lease_expires_at = None

        email.save(
            update_fields=[
                "status",
                "failure_reason",
                "sent_at",
                "lease_expires_at",
                "updated_at",
            ]
        )


def mark_superseded(email_id, claimed_attempt):
    with transaction.atomic():
        email = lock_owned_email(
            email_id,
            claimed_attempt,
            [ResultEmail.Status.SENDING],
        )

        if email is None:
            return

        email.status = ResultEmail.Status.SUPERSEDED
        email.lease_expires_at = None

        email.save(
            update_fields=[
                "status",
                "lease_expires_at",
                "updated_at",
            ]
        )


def mark_failed(email_id, claimed_attempt, reason, error, retry):
    now = timezone.now()

    with transaction.atomic():
        email = lock_owned_email(
            email_id,
            claimed_attempt,
            [ResultEmail.Status.SENDING],
        )

        if email is None:
            return

        email.failure_reason = reason
        email.last_error = error[:MAX_ERROR_LENGTH]
        email.lease_expires_at = None

        if retry and email.attempts < email.max_attempts:
            delay = RETRY_DELAYS[
                min(email.attempts - 1, len(RETRY_DELAYS) - 1)
            ]

            email.status = ResultEmail.Status.QUEUED
            email.run_after = now + delay
        else:
            email.status = ResultEmail.Status.FAILED

        email.save(
            update_fields=[
                "status",
                "failure_reason",
                "last_error",
                "lease_expires_at",
                "run_after",
                "updated_at",
            ]
        )


def deliver_email(email, claimed_attempt):
    current_version = (
        Result.objects
        .filter(pk=email.result_id)
        .values_list("version", flat=True)
        .first()
    )

    # The mark changed after this email was scheduled.
    if current_version != email.result_version:
        mark_superseded(email.pk, claimed_attempt)
        return

    if not email.recipient:
        mark_failed(
            email.pk,
            claimed_attempt,
            ResultEmail.FailureReason.MISSING_RECIPIENT,
            "No recipient address.",
            retry=False,
        )
        return

    # One recipient per message: students never see each other's results.
    message = EmailMessage(
        subject=email.subject,
        body=email.body,
        to=[email.recipient],
        headers={
            "Message-ID": message_id(email),
        },
    )

    try:
        message.send()
    except SMTPRecipientsRefused as exc:
        logger.warning(
            "Result email %s refused by mail server",
            email.pk,
        )
        mark_failed(
            email.pk,
            claimed_attempt,
            ResultEmail.FailureReason.RECIPIENT_REFUSED,
            f"{type(exc).__name__}: {exc}",
            retry=False,
        )
        return
    except Exception as exc:
        logger.exception(
            "Result email %s failed on attempt %s",
            email.pk,
            claimed_attempt,
        )
        mark_failed(
            email.pk,
            claimed_attempt,
            ResultEmail.FailureReason.PROVIDER_ERROR,
            f"{type(exc).__name__}: {exc}",
            retry=True,
        )
        return

    mark_sent(email.pk, claimed_attempt)


def recover_expired_sends():
    # Whether a send that outlived its lease reached the student is unknown.
    # It is failed rather than resent, so a student is never emailed twice
    # without the lecturer choosing to retry.
    now = timezone.now()

    return ResultEmail.objects.filter(
        status=ResultEmail.Status.SENDING,
        lease_expires_at__lt=now,
    ).update(
        status=ResultEmail.Status.FAILED,
        failure_reason=ResultEmail.FailureReason.DELIVERY_UNKNOWN,
        lease_expires_at=None,
        updated_at=now,
    )


def process_next_email():
    email = claim_next_email()

    if email is None:
        return False

    deliver_email(email, email.attempts)

    return True
