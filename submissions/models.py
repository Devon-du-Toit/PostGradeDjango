from django.db import models
from django.db.models import Q
from django.utils import timezone

from assessments.models import Assessment
from students.models import Enrollment


class Submission(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        MATCHED = "matched", "Matched"
        NEEDS_VERIFICATION = "needs_verification","Needs verification" #check change
        VERIFIED = "verified", "Verified"
        MARKED = "marked", "Marked"
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

    def __str__(self):
        return self.original_filename

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

    raw_text = models.TextField(
        blank=True,
    )

    raw_candidate = models.CharField(
        max_length=50,
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

