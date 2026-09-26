from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from distribution.models import ResultEmail
from submissions.emailing import build_result_email


RELEASE_AUTOMATIC = "automatic"
RELEASE_APPROVAL = "approval"


def release_policy():
    policy = getattr(
        settings,
        "RESULT_EMAIL_RELEASE_POLICY",
        RELEASE_AUTOMATIC,
    )

    if policy not in (RELEASE_AUTOMATIC, RELEASE_APPROVAL):
        raise ImproperlyConfigured(
            "RESULT_EMAIL_RELEASE_POLICY must be "
            f"'{RELEASE_AUTOMATIC}' or '{RELEASE_APPROVAL}'."
        )

    return policy


def idempotency_key(result):
    return f"result-{result.pk}-v{result.version}"


def schedule_result_email(result):
    # Call inside the transaction that saved the result, so the email
    # record commits (or rolls back) together with the mark.
    key = idempotency_key(result)

    existing = ResultEmail.objects.filter(
        idempotency_key=key,
    ).first()

    if existing is not None:
        return existing

    now = timezone.now()

    # An older mark that has not gone out must never be sent.
    ResultEmail.objects.filter(
        result=result,
        status__in=ResultEmail.UNSENT_STATUSES,
    ).exclude(
        result_version=result.version,
    ).update(
        status=ResultEmail.Status.SUPERSEDED,
        lease_expires_at=None,
        updated_at=now,
    )

    subject, body = build_result_email(result)
    recipient = result.enrollment.student.email

    if not recipient:
        status = ResultEmail.Status.FAILED
        failure_reason = ResultEmail.FailureReason.MISSING_RECIPIENT
    elif release_policy() == RELEASE_APPROVAL:
        status = ResultEmail.Status.AWAITING_APPROVAL
        failure_reason = ""
    else:
        status = ResultEmail.Status.QUEUED
        failure_reason = ""

    try:
        # Savepoint: a concurrent duplicate only rolls back this insert.
        with transaction.atomic():
            return ResultEmail.objects.create(
                result=result,
                result_version=result.version,
                idempotency_key=key,
                recipient=recipient,
                subject=subject,
                body=body,
                status=status,
                failure_reason=failure_reason,
            )
    except IntegrityError:
        return ResultEmail.objects.get(
            idempotency_key=key,
        )


def approve_email(email_id, user):
    now = timezone.now()

    with transaction.atomic():
        email = (
            ResultEmail.objects
            .select_for_update()
            .select_related("result")
            .get(pk=email_id)
        )

        if email.status != ResultEmail.Status.AWAITING_APPROVAL:
            raise ValidationError(
                "Only emails awaiting approval can be approved."
            )

        if email.result_version != email.result.version:
            raise ValidationError(
                "This email is for an outdated mark."
            )

        email.status = ResultEmail.Status.QUEUED
        email.approved_by = user
        email.approved_at = now
        email.run_after = now

        email.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "run_after",
                "updated_at",
            ]
        )

    return email


def approve_assessment_emails(assessment, user):
    now = timezone.now()

    return ResultEmail.objects.filter(
        result__assessment=assessment,
        status=ResultEmail.Status.AWAITING_APPROVAL,
        result_version=F("result__version"),
    ).update(
        status=ResultEmail.Status.QUEUED,
        approved_by=user,
        approved_at=now,
        run_after=now,
        updated_at=now,
    )


def retry_email(email_id, confirm_duplicate=False):
    now = timezone.now()

    with transaction.atomic():
        email = (
            ResultEmail.objects
            .select_for_update()
            .select_related("result__enrollment__student")
            .get(pk=email_id)
        )

        if email.status != ResultEmail.Status.FAILED:
            raise ValidationError(
                "Only failed emails can be retried."
            )

        if email.result_version != email.result.version:
            raise ValidationError(
                "This email is for an outdated mark."
            )

        if (
            email.failure_reason
            == ResultEmail.FailureReason.DELIVERY_UNKNOWN
            and not confirm_duplicate
        ):
            raise ValidationError(
                "This email may already have been delivered. "
                "Retry with confirm_duplicate to send it again."
            )

        # Pick up a corrected address.
        recipient = email.result.enrollment.student.email

        if not recipient:
            raise ValidationError(
                "The student has no email address."
            )

        email.recipient = recipient
        email.status = ResultEmail.Status.QUEUED
        email.failure_reason = ""
        email.last_error = ""
        email.attempts = 0
        email.run_after = now
        email.lease_expires_at = None

        email.save(
            update_fields=[
                "recipient",
                "status",
                "failure_reason",
                "last_error",
                "attempts",
                "run_after",
                "lease_expires_at",
                "updated_at",
            ]
        )

    return email
