from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from assessments.models import Assessment
from students.models import Enrollment

UNCHANGED = object()


class SubmissionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            models.Q(enrollment__isnull=True)
            | models.Q(
                enrollment__withdrawn_at__isnull=True,
                enrollment__student__archived_at__isnull=True,
            ),
            archived_at__isnull=True,
            superseded_at__isnull=True,
            assessment__archived_at__isnull=True,
            assessment__course__archived_at__isnull=True,
        )


class Submission(models.Model):
    objects = SubmissionQuerySet.as_manager()

    class RecognitionMethod(models.TextChoices):
        OCR = "ocr", "Handwritten digits (OCR)"
        BUBBLE = "bubble", "Filled bubbles"

    archived_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_scripts",
    )

    qr_group_key = models.CharField(max_length=240, blank=True)
    qr_metadata = models.JSONField(default=dict, blank=True)
    qr_review_issues = models.JSONField(default=list, blank=True)

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
        on_delete=models.PROTECT,
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

    def clean(self):
        if self.enrollment_id is not None:
            if (
                self.enrollment.course_id != self.assessment.course_id
                or self.enrollment.student.owner_id != self.assessment.course.owner_id
            ):
                raise ValidationError(
                    "Enrollment must belong to the assessment course and owner."
                )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

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
                new_enrollment = (
                    Enrollment.objects.active()
                    .select_related("student")
                    .select_for_update(of=("self",))
                    .filter(pk=new_enrollment.pk)
                    .first()
                )
                if new_enrollment is None:
                    raise ValueError(
                        "Enrollment no longer exists. Reload and select a current student."
                    )
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
            models.UniqueConstraint(
                fields=["assessment", "enrollment"],
                condition=Q(
                    status="verified",
                    enrollment__isnull=False,
                    archived_at__isnull=True,
                    superseded_at__isnull=True,
                ),
                name="one_current_verified_script",
            ),
            models.UniqueConstraint(
                fields=["assessment", "qr_group_key"],
                condition=~Q(qr_group_key="")
                & Q(archived_at__isnull=True, superseded_at__isnull=True),
                name="unique_assessment_qr_group",
            ),
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
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
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

    previous_identity = models.JSONField(default=dict, blank=True)
    new_identity = models.JSONField(default=dict, blank=True)

    def save(self, *args, **kwargs):
        from submissions.identity import enrollment_identity

        if self._state.adding:
            self.previous_identity = enrollment_identity(self.previous_enrollment)
            self.new_identity = enrollment_identity(self.new_enrollment)
        else:
            stored = (
                SubmissionAudit.objects.filter(pk=self.pk)
                .values("previous_identity", "new_identity")
                .first()
            )
            if stored and (
                stored["previous_identity"] != self.previous_identity
                or stored["new_identity"] != self.new_identity
            ):
                raise ValidationError("Audit identity snapshots cannot be changed.")
        return super().save(*args, **kwargs)

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


class ScriptPage(models.Model):
    upload = models.ForeignKey(
        "ScriptUpload", on_delete=models.CASCADE, related_name="pages"
    )
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="pages"
    )
    file = models.FileField(upload_to="script-pages/%Y/%m/%d/")
    source_page = models.PositiveIntegerField()
    source_filename = models.CharField(max_length=255)
    qr_fields = models.JSONField(default=dict, blank=True)
    qr_status = models.CharField(max_length=32)
    page_label = models.CharField(max_length=20, blank=True)
    excluded = models.BooleanField(default=False)
    review_history = models.JSONField(default=list, blank=True)
    recognition_outcome = models.CharField(max_length=40, blank=True)
    quality_issues = models.JSONField(default=list, blank=True)
    suggested_enrollment = models.ForeignKey(
        Enrollment, on_delete=models.SET_NULL, null=True, blank=True
    )
    linked_enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="script_pages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class ScriptUpload(models.Model):
    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="script_uploads"
    )
    file = models.FileField(upload_to="script-uploads/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class SubmissionFileRevision(models.Model):
    status = models.CharField(max_length=20)
    student_identity = models.JSONField(default=dict, blank=True)
    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="file_revisions"
    )
    file = models.FileField(upload_to="retained-script-revisions/")
    version = models.PositiveIntegerField()
    original_filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field)
                for field in (
                    "submission_id",
                    "file",
                    "version",
                    "original_filename",
                    "student_identity",
                    "status",
                )
            ):
                raise ValidationError("Retained file revisions are immutable.")
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["-version", "-pk"]
