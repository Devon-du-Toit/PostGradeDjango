from django.db import models

from assessments.models import Assessment
from students.models import Enrollment


class Submission(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        MATCHED = "matched", "Matched"
        NEEDS_VERIFICATION = (
            "needs_verification",
            "Needs verification",
        )
        VERIFIED = "verified", "Verified"
        MARKED = "marked", "Marked"

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="submissions",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        related_name="submissions",
        null=True,
        blank=True,
    )

    file = models.FileField(
        upload_to="submissions/%Y/%m/%d/",
    )

    original_filename = models.CharField(
        max_length=255,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADED,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.original_filename


class SubmissionAudit(models.Model):
    """Records every status change on a Submission.

    Provides the audit trail required by issue #6: actor, timestamp,
    previous/new status, previous/new enrollment, and a reason.
    """

    submission = models.ForeignKey(
        Submission,
        on_delete=models.CASCADE,
        related_name="audit_entries",
    )

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submission_audits",
        help_text="User who made the change. Null for system-initiated changes.",
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    previous_status = models.CharField(
        max_length=20,
        choices=Submission.Status.choices,
        null=True,
        blank=True,
        help_text="Null on creation.",
    )

    new_status = models.CharField(
        max_length=20,
        choices=Submission.Status.choices,
    )

    previous_enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    new_enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    reason = models.TextField(
        blank=True,
        help_text="Optional explanation for manual corrections.",
    )

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["submission", "-timestamp"]),
        ]

    def __str__(self):
        return f"Audit #{self.pk} for submission {self.submission_id}"