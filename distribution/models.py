from django.conf import settings
from django.db import models
from django.utils import timezone

from submissions.models import Submission
from students.models import Enrollment


class ScriptEmail(models.Model):
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
        ATTACHMENT_UNAVAILABLE = (
            "attachment_unavailable",
            "Script attachment unavailable",
        )
        DELIVERY_UNKNOWN = (
            "delivery_unknown",
            "Worker stopped while sending; delivery unknown",
        )

    UNSENT_STATUSES = [Status.AWAITING_APPROVAL, Status.QUEUED, Status.FAILED]
    # Null only for retained historical emails or deleted submissions.
    submission = models.ForeignKey(
        Submission,
        on_delete=models.SET_NULL,
        related_name="emails",
        null=True,
        blank=True,
    )
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        related_name="script_emails",
        null=True,
        blank=True,
    )
    submission_version = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=100, unique=True)
    # Immutable copy of the verified file: retries cannot attach a replacement.
    attachment = models.FileField(upload_to="script-emails/%Y/%m/%d/", blank=True)
    attachment_filename = models.CharField(max_length=255, blank=True)

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
                name="script_email_claim_idx",
            ),
        ]

    def __str__(self):
        return f"{self.idempotency_key} - {self.status}"
