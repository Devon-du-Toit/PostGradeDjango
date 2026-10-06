import logging
import mimetypes
from datetime import timedelta
from email.utils import parseaddr
from smtplib import SMTPRecipientsRefused

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from distribution.models import ScriptEmail
from distribution.services import is_current

logger = logging.getLogger(__name__)

# Covers one SMTP send (EMAIL_TIMEOUT) with a wide margin.
LEASE_DURATION = timedelta(minutes=2)

RETRY_DELAYS = [
    timedelta(minutes=1),
    timedelta(minutes=4),
]

MAX_ERROR_LENGTH = 2000


def message_id(email):
    # Stable per verified script version: retries share an ID,
    # so mail clients can recognise a repeat.
    domain = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].partition("@")[2]

    return f"<{email.idempotency_key}@{domain or 'postgrade.local'}>"


def claim_next_email():
    now = timezone.now()

    with transaction.atomic():
        email = (
            ScriptEmail.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                status=ScriptEmail.Status.QUEUED,
                submission__isnull=False,
                run_after__lte=now,
                submission__assessment__archived_at__isnull=True,
                submission__assessment__course__archived_at__isnull=True,
            )
            .order_by("run_after")
            .first()
        )

        if email is None:
            return None

        email.status = ScriptEmail.Status.SENDING
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
    email = ScriptEmail.objects.select_for_update().get(
        pk=email_id,
    )

    if email.status not in statuses or email.attempts != claimed_attempt:
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
                ScriptEmail.Status.SENDING,
                ScriptEmail.Status.FAILED,
            ],
        )

        if email is None:
            return

        if (
            email.status == ScriptEmail.Status.FAILED
            and email.failure_reason != ScriptEmail.FailureReason.DELIVERY_UNKNOWN
        ):
            return

        email.status = ScriptEmail.Status.SENT
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
            [ScriptEmail.Status.SENDING],
        )

        if email is None:
            return

        email.status = ScriptEmail.Status.SUPERSEDED
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
            [ScriptEmail.Status.SENDING],
        )

        if email is None:
            return

        email.failure_reason = reason
        email.last_error = error[:MAX_ERROR_LENGTH]
        email.lease_expires_at = None

        if not is_current(email):
            email.status = ScriptEmail.Status.SUPERSEDED
        elif retry and email.attempts < email.max_attempts:
            delay = RETRY_DELAYS[min(email.attempts - 1, len(RETRY_DELAYS) - 1)]

            email.status = ScriptEmail.Status.QUEUED
            email.run_after = now + delay
        else:
            email.status = ScriptEmail.Status.FAILED

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
    if not is_current(email):
        mark_superseded(email.pk, claimed_attempt)
        return

    if not email.recipient:
        mark_failed(
            email.pk,
            claimed_attempt,
            ScriptEmail.FailureReason.MISSING_RECIPIENT,
            "No recipient address.",
            retry=False,
        )
        return

    # One recipient and one verified script per message.
    message = EmailMessage(
        subject=email.subject,
        body=email.body,
        to=[email.recipient],
        headers={
            "Message-ID": message_id(email),
        },
    )

    try:
        with email.attachment.open("rb") as attachment:
            content = attachment.read()
        if not content:
            raise ValueError("Empty attachment")
        message.attach(
            email.attachment_filename,
            content,
            mimetypes.guess_type(email.attachment_filename)[0]
            or "application/octet-stream",
        )
    except (OSError, ValueError) as exc:
        mark_failed(
            email.pk,
            claimed_attempt,
            ScriptEmail.FailureReason.ATTACHMENT_UNAVAILABLE,
            f"{type(exc).__name__}: attachment unavailable",
            retry=False,
        )
        return

    try:
        if message.send() != 1:
            raise RuntimeError("Email backend did not accept the message")
    except SMTPRecipientsRefused as exc:
        logger.warning(
            "Script email %s refused by mail server",
            email.pk,
        )
        mark_failed(
            email.pk,
            claimed_attempt,
            ScriptEmail.FailureReason.RECIPIENT_REFUSED,
            f"{type(exc).__name__}: {exc}",
            retry=False,
        )
        return
    except Exception as exc:
        logger.exception(
            "Script email %s failed on attempt %s",
            email.pk,
            claimed_attempt,
        )
        mark_failed(
            email.pk,
            claimed_attempt,
            ScriptEmail.FailureReason.PROVIDER_ERROR,
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

    return ScriptEmail.objects.filter(
        status=ScriptEmail.Status.SENDING,
        lease_expires_at__lt=now,
    ).update(
        status=ScriptEmail.Status.FAILED,
        failure_reason=ScriptEmail.FailureReason.DELIVERY_UNKNOWN,
        lease_expires_at=None,
        updated_at=now,
    )


def process_next_email():
    email = claim_next_email()

    if email is None:
        return False

    deliver_email(email, email.attempts)

    return True
