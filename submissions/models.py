from django.db import transaction
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from assessments.models import Assessment
from students.models import Enrollment

UNCHANGED = object()


class SubmissionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            assessment__archived_at__isnull=True,
            assessment__course__archived_at__isnull=True,
        )


class Submission(models.Model):
    objects = SubmissionQuerySet.as_manager()

    class RecognitionMethod(models.TextChoices):
        OCR = "ocr", "Handwritten digits (OCR)"
        BUBBLE = "bubble", "Filled bubbles"

    recognition_method = models.CharField(
        max_length=20,
        choices=RecognitionMethod.choices,
        default=RecognitionMethod.OCR,
    )

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        MATCHED = "matched", "Matched"
        NEEDS_VERIFICATION = "needs_verification", "Needs verification"
        VERIFIED = "verified", "Verified"
        PROCESSING = "processing", "Processing"
        RECOGNITION_FAILED = "recognition_failed", "Recognition failed"

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

    version = models.PositiveIntegerField(
        default=0,
    )

    def __str__(self):
        return self.original_filename

    # "processing" is also reached by retrying recognition and by replacing
    # the file; "recognition_failed" is left by retrying or verifying by hand.
    ALLOWED_TRANSITIONS = {
        "uploaded": {"processing", "matched", "needs_verification"},
        "processing": {
            "processing",
            "matched",
            "needs_verification",
            "verified",
            "recognition_failed",
        },
        "matched": {"verified", "needs_verification", "processing"},
        "needs_verification": {"verified", "processing"},
        "recognition_failed": {"verified", "processing"},
        "verified": {"verified", "processing"},
    }

    def record_status_change(
        self,
        actor,
        new_status,
        reason="",
        new_enrollment=UNCHANGED,
        expected_version=None,
    ):
        with transaction.atomic():
            locked = Submission.objects.select_for_update().get(pk=self.pk)
            previous_status = locked.status
            previous_enrollment = locked.enrollment

            if expected_version is not None and expected_version != locked.version:
                raise ValueError("This submission has changed. Reload and try again.")
            if (
                previous_status == self.Status.VERIFIED
                and locked.enrollment_id is not None
                and new_status == self.Status.VERIFIED
                and new_enrollment is not UNCHANGED
                and getattr(new_enrollment, "pk", None) != locked.enrollment_id
                and (expected_version is None or not reason.strip())
            ):
                raise ValueError("Identity corrections require a version and a reason.")
            if new_enrollment is not UNCHANGED and new_enrollment is not None:
                if new_enrollment.course_id != locked.assessment.course_id:
                    raise ValueError(
                        "Enrollment must belong to the submission's course."
                    )

            allowed = self.ALLOWED_TRANSITIONS.get(previous_status, set())
            if new_status not in allowed:
                raise ValueError(
                    f"Illegal transition from {previous_status} to {new_status}"
                )

            locked.status = new_status
            locked.version += 1
            if new_enrollment is not UNCHANGED:
                locked.enrollment = new_enrollment
            locked.save(update_fields=["status", "enrollment", "version", "updated_at"])

            audit = SubmissionAudit.objects.create(
                submission=locked,
                actor=actor,
                previous_status=previous_status,
                new_status=new_status,
                previous_enrollment=previous_enrollment,
                new_enrollment=locked.enrollment,
                reason=reason,
            )

        # Callers serialize/use this instance after the transition. Keep it
        # consistent with the row actually written, including its enrollment.
        self.status = locked.status
        self.enrollment = locked.enrollment
        self.version = locked.version
        self.updated_at = locked.updated_at
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
                        "processing",
                        "recognition_failed",
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


class RecognitionAttempt(models.Model):
    class Method(models.TextChoices):
        OCR = "ocr", "OCR"
        BUBBLE = "bubble", "Bubble"

    class Outcome(models.TextChoices):
        MATCHED = "matched", "Matched"
        NO_MATCH = "no_match", "No match"
        NO_CANDIDATE = "no_candidate", "No candidate"
        REGION_NOT_FOUND = (
            "region_not_found",
            "Region not found",
        )
        IMAGE_UNUSABLE = "image_unusable", "Image unusable"
        ERROR = "error", "Error"

    class ConfidenceType(models.TextChoices):
        NONE = "none", "None"
        OCR_SCORE = "ocr_score", "OCR score"
        BUBBLE_MARGIN = "bubble_margin", "Bubble margin"

    submission = models.ForeignKey(
        Submission,
        on_delete=models.CASCADE,
        related_name="recognition_attempts",
    )

    method = models.CharField(
        max_length=20,
        choices=Method.choices,
    )

    outcome = models.CharField(
        max_length=20,
        choices=Outcome.choices,
    )

    processing_version = models.CharField(
        max_length=50,
    )

    template_version = models.CharField(max_length=50, blank=True)
    column_scores = models.JSONField(default=list, blank=True)

    raw_text = models.TextField(
        blank=True,
    )

    # First candidate only. Kept so existing API clients do not break;
    # raw_candidates holds every candidate matching evaluated.
    raw_candidate = models.CharField(
        max_length=50,
        blank=True,
    )

    # [{"value": "37279432", "confidence": 0.97}, ...]
    raw_candidates = models.JSONField(
        default=list,
        blank=True,
    )

    suggested_enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    suggested_student_number = models.CharField(
        max_length=50,
        blank=True,
    )

    confidence = models.FloatField(
        null=True,
        blank=True,
    )

    confidence_type = models.CharField(
        max_length=20,
        choices=ConfidenceType.choices,
        default=ConfidenceType.NONE,
    )

    column_ambiguity = models.JSONField(
        default=list,
        blank=True,
    )

    region = models.JSONField(
        null=True,
        blank=True,
    )

    region_image = models.FileField(
        upload_to="recognition/%Y/%m/%d/",
        blank=True,
    )

    quality_issues = models.JSONField(
        default=list,
        blank=True,
    )

    # Set when outcome is "error". The type is safe to expose; the
    # message can contain server paths and stays internal.
    error_type = models.CharField(
        max_length=100,
        blank=True,
    )

    error_message = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["submission", "-created_at"],
                name="recognition_latest_idx",
            ),
        ]

    def __str__(self):
        return f"{self.submission} - {self.method} - {self.outcome}"


class RecognitionJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE_STATUSES = [
        Status.QUEUED,
        Status.RUNNING,
    ]

    submission = models.ForeignKey(
        Submission,
        on_delete=models.CASCADE,
        related_name="recognition_jobs",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
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

    last_error = models.TextField(
        blank=True,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    finished_at = models.DateTimeField(
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
        constraints = [
            models.UniqueConstraint(
                fields=["submission"],
                condition=Q(status__in=["queued", "running"]),
                name="one_active_recognition_job_per_submission",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "run_after"],
                name="recognition_job_claim_idx",
            ),
        ]

    def __str__(self):
        return f"{self.submission} - {self.status}"
