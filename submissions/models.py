from django.db import transaction
from django.conf import settings
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
    ALLOWED_TRANSITIONS = {
        "uploaded": {"matched", "needs_verification"},
        "matched": {"verified", "needs_verification"},
        "needs_verification": {"verified"},
        "verified": {"marked"},
        "marked": set(),
    } 
    def record_status_change(
        self,
        actor,
        new_status,
        reason="",
    ):
        allowed = self.ALLOWED_TRANSITIONS.get(
            self.status, set()
        )
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition from {self.status} to {new_status}"
            )

        with transaction.atomic():
            locked = (
                Submission.objects
                .select_for_update()
                .get(pk=self.pk)
            )
            previous_status = locked.status
            previous_enrollment = locked.enrollment

            audit = SubmissionAudit.objects.create(
                submission=self,
                actor=actor,
                previous_status=previous_status,
                new_status=new_status,
                previous_enrollment=previous_enrollment,
                new_enrollment=self.enrollment,
                reason=reason,
            )

            self.status = new_status
            self.save(update_fields=["status"])

        return audit

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "uploaded",
                        "matched",
                        "needs_verification",
                        "verified",
                        "marked",
                    ]
                ),
                name="submission_status_valid",
            ),
        ]

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
	settings.AUTH_USER_MODEL,
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


