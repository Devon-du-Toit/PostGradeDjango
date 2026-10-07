from hashlib import sha256
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from assessments.models import Assessment
from distribution.models import ScriptEmail
from submissions.emailing import build_script_email
from submissions.lifecycle import lock_submission_scope
from submissions.models import Submission

RELEASE_AUTOMATIC = "automatic"
RELEASE_APPROVAL = "approval"


def release_policy():
    policy = getattr(settings, "SCRIPT_EMAIL_RELEASE_POLICY", RELEASE_AUTOMATIC)
    if policy not in (RELEASE_AUTOMATIC, RELEASE_APPROVAL):
        raise ImproperlyConfigured(
            "SCRIPT_EMAIL_RELEASE_POLICY must be 'automatic' or 'approval'."
        )
    return policy


def is_current(email):
    return (
        Submission.objects.active()
        .filter(
            pk=email.submission_id,
            status=Submission.Status.VERIFIED,
            version=email.submission_version,
            enrollment_id=email.enrollment_id,
            enrollment__student__email=email.recipient,
        )
        .exists()
        and email.enrollment_id is not None
    )


def supersede_submission_emails(submission):
    ScriptEmail.objects.filter(
        submission=submission, status__in=ScriptEmail.UNSENT_STATUSES
    ).update(
        status=ScriptEmail.Status.SUPERSEDED,
        lease_expires_at=None,
        updated_at=timezone.now(),
    )


def schedule_script_email(
    submission, *, expected_version=None, expected_enrollment_id=None
):
    attachment = None
    try:
        with transaction.atomic():
            lock_submission_scope(submission.pk)
            # Serialize requests with verification and replacement; lock parents
            # too, so archiving cannot admit new work after its cancellation.
            submission = (
                Submission.objects.active()
                .select_related(
                    "assessment__course",
                    "enrollment__student",
                )
                .select_for_update(of=("self",))
                .get(pk=submission.pk)
            )
            if expected_version is not None and (
                submission.version != expected_version
                or submission.enrollment_id != expected_enrollment_id
            ):
                raise ValidationError("This email is for an outdated verified script.")
            if (
                submission.status != Submission.Status.VERIFIED
                or submission.enrollment_id is None
            ):
                raise ValidationError("Verify the student before emailing the script.")
            if (
                submission.enrollment.withdrawn_at is not None
                or submission.enrollment.student.archived_at is not None
            ):
                raise ValidationError(
                    "Restore class membership before emailing scripts."
                )
            if submission.enrollment.course_id != submission.assessment.course_id:
                raise ValidationError(
                    "The verified student must belong to the assessment's course."
                )
            if submission.qr_group_key:
                from submissions.qr import group_issues

                if group_issues(submission):
                    raise ValidationError(
                        "Resolve QR page review before emailing the script."
                    )
            recipient = submission.enrollment.student.email
            matching = ScriptEmail.objects.filter(
                submission=submission,
                submission_version=submission.version,
                enrollment_id=submission.enrollment_id,
                recipient=recipient,
            )
            # Match the immutable target/version, not the key spelling: legacy
            # sent, pending and uncertain rows must remain idempotent on upgrade.
            available = matching.exclude(status=ScriptEmail.Status.SUPERSEDED)
            existing = available.filter(status=ScriptEmail.Status.SENT).first()
            if existing is None:
                existing = available.order_by("pk").first()
            if existing is not None:
                return existing
            if matching.filter(
                failure_reason=ScriptEmail.FailureReason.DELIVERY_UNKNOWN
            ).exists():
                raise ValidationError(
                    "An earlier delivery to this address has an unknown outcome. Review the retained delivery record before requesting another send."
                )
            last_cancelled = (
                matching.filter(status=ScriptEmail.Status.SUPERSEDED)
                .order_by("-pk")
                .first()
            )
            # 128 bits of SHA-256 plus numeric generation fit the existing
            # 100-character key even for maximum bigint IDs/integer versions.
            contact_key = sha256(recipient.encode("utf-8")).hexdigest()[:32]
            key = f"submission-{submission.pk}-v{submission.version}-to-{contact_key}"
            if last_cancelled is not None:
                key += f"-g{last_cancelled.pk}"
            if not submission.file:
                raise ValidationError("The script file is unavailable.")
            try:
                with submission.file.open("rb") as source:
                    content = source.read()
            except (OSError, FileNotFoundError) as exc:
                raise ValidationError("The script file is unavailable.") from exc
            if not content:
                raise ValidationError("The script file is empty.")
            subject, body = build_script_email(submission)
            recipient = submission.enrollment.student.email
            email = ScriptEmail(
                submission=submission,
                enrollment=submission.enrollment,
                submission_version=submission.version,
                idempotency_key=key,
                recipient=recipient,
                subject=subject,
                body=body,
                attachment_filename=PurePath(
                    submission.original_filename.replace("\\", "/")
                ).name,
                status=(
                    ScriptEmail.Status.FAILED
                    if not recipient
                    else (
                        ScriptEmail.Status.AWAITING_APPROVAL
                        if release_policy() == RELEASE_APPROVAL
                        else ScriptEmail.Status.QUEUED
                    )
                ),
                failure_reason=(
                    ScriptEmail.FailureReason.MISSING_RECIPIENT if not recipient else ""
                ),
            )
            email.attachment.save(
                email.attachment_filename or "script", ContentFile(content), save=False
            )
            attachment = email.attachment
            supersede_submission_emails(submission)
            email.save()
            return email
    except Submission.DoesNotExist as exc:
        raise ValidationError("The submission is archived or unavailable.") from exc
    except Exception:
        if attachment is not None:
            attachment.storage.delete(attachment.name)
        raise


def approve_email(email_id, user):
    with transaction.atomic():
        email = ScriptEmail.objects.select_for_update().get(pk=email_id)
        if not is_current(email):
            raise ValidationError(
                "This email is for an unavailable or outdated verified script."
            )
        if email.status != ScriptEmail.Status.AWAITING_APPROVAL:
            raise ValidationError("Only emails awaiting approval can be approved.")
        email.status = ScriptEmail.Status.QUEUED
        email.approved_by = user
        email.approved_at = email.run_after = timezone.now()
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
    with transaction.atomic():
        if (
            not Assessment.objects.active()
            .select_for_update()
            .filter(pk=assessment.pk)
            .exists()
        ):
            raise ValidationError("Archived assessment emails cannot be approved.")
        return ScriptEmail.objects.filter(
            submission__in=Submission.objects.active(),
            submission__assessment=assessment,
            submission__status=Submission.Status.VERIFIED,
            submission_version=F("submission__version"),
            enrollment=F("submission__enrollment"),
            status=ScriptEmail.Status.AWAITING_APPROVAL,
        ).update(
            status=ScriptEmail.Status.QUEUED,
            approved_by=user,
            approved_at=timezone.now(),
            run_after=timezone.now(),
            updated_at=timezone.now(),
        )


def retry_email(email_id, confirm_duplicate=False):
    # A corrected destination creates a fresh immutable snapshot. Acquire parent
    # locks through scheduling before its email-row lock, avoiding the reverse
    # order used by archive/withdrawal to supersede unsent messages.
    previous = ScriptEmail.objects.select_related(
        "enrollment__student", "submission"
    ).get(pk=email_id)
    if (
        previous.enrollment_id
        and previous.recipient != previous.enrollment.student.email
    ):
        if previous.status != ScriptEmail.Status.FAILED:
            raise ValidationError("Only failed emails can be retried.")
        if (
            previous.failure_reason == ScriptEmail.FailureReason.DELIVERY_UNKNOWN
            and not confirm_duplicate
        ):
            raise ValidationError(
                "This email may already have been delivered. Retry with confirm_duplicate to send it again."
            )
        return schedule_script_email(
            previous.submission,
            expected_version=previous.submission_version,
            expected_enrollment_id=previous.enrollment_id,
        )
    with transaction.atomic():
        email = (
            ScriptEmail.objects.select_for_update(of=("self",))
            .select_related("enrollment__student")
            .get(pk=email_id)
        )
        if not is_current(email):
            raise ValidationError(
                "This email is for an unavailable or outdated verified script."
            )
        if email.status != ScriptEmail.Status.FAILED:
            raise ValidationError("Only failed emails can be retried.")
        if (
            email.failure_reason == ScriptEmail.FailureReason.DELIVERY_UNKNOWN
            and not confirm_duplicate
        ):
            raise ValidationError(
                "This email may already have been delivered. Retry with confirm_duplicate to send it again."
            )
        if not email.enrollment.student.email:
            raise ValidationError("The student has no email address.")
        email.recipient = email.enrollment.student.email
        # A missing recipient must not bypass an approval release policy.
        email.status = (
            ScriptEmail.Status.AWAITING_APPROVAL
            if release_policy() == RELEASE_APPROVAL and not email.approved_at
            else ScriptEmail.Status.QUEUED
        )
        email.failure_reason = email.last_error = ""
        email.attempts = 0
        email.run_after = timezone.now()
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
