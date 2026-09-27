from django.conf import settings
from django.db import models
from django.utils import timezone

from assessments.models import Result


class ResultEmail(models.Model):
    class Status(models.TextChoices):
        AWAITING_APPROVAL = (
            "awaiting_approval",
            "Awaiting approval",
        )
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SUPERSEDED = "superseded", "Superseded"

    class FailureReason(models.TextChoices):
        MISSING_RECIPIENT = (
            "missing_recipient",
            "Student has no email address",
        )
        RECIPIENT_REFUSED = (
            "recipient_refused",
            "Mail server refused the recipient",
        )
        PROVIDER_ERROR = (
            "provider_error",
            "Mail server error",
        )
        DELIVERY_UNKNOWN = (
            "delivery_unknown",
            "Worker stopped while sending; delivery unknown",
        )

    # Not yet sent, so a newer result version may still replace them.
    UNSENT_STATUSES = [
        Status.AWAITING_APPROVAL,
        Status.QUEUED,
        Status.FAILED,
    ]

    result = models.ForeignKey(
        Result,
        on_delete=models.CASCADE,
        related_name="emails",
    )

    result_version = models.PositiveIntegerField()

    # One email per result version: repeated requests reuse this record.
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
    )

    # Snapshot of exactly what will be (or was) sent, for review.
    recipient = models.EmailField(
        blank=True,
    )

    subject = models.CharField(
        max_length=255,
    )

    body = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
    )

    failure_reason = models.CharField(
        max_length=30,
        choices=FailureReason.choices,
        blank=True,
    )

    # Full provider error for administrators; never returned by the API.
    last_error = models.TextField(
        blank=True,
    )

    attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    max_attempts = models.PositiveSmallIntegerField(
        default=3,
    )

    run_after = models.DateTimeField(
        default=timezone.now,
    )

    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "run_after"],
                name="result_email_claim_idx",
            ),
        ]

    def __str__(self):
        return f"{self.idempotency_key} - {self.status}"
