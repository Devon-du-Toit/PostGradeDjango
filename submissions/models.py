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
