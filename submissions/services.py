"""Persistence for validated submission uploads and file replacements.

Request parsing/content validation stays in serializers. Lock order, audit/version
updates, job cancellation and after-commit storage cleanup stay together here.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from distribution.services import supersede_submission_emails
from submissions.jobs import cancel_active_jobs, enqueue_recognition
from submissions.lifecycle import lock_active_assessment, lock_submission_scope
from submissions.models import RecognitionJob, Submission, SubmissionAudit
from submissions.signals import delete_file_after_commit


def create_submission(validated_data, actor):
    if validated_data["assessment"].expected_qr_page_labels:
        from submissions.qr import create_qr_submissions

        return create_qr_submissions(validated_data, actor)
    validated_data = dict(validated_data)
    validated_data.pop("version", None)
    validated_data["enrollment"] = None
    uploaded_file = validated_data["file"]
    validated_data["original_filename"] = uploaded_file.name
    validated_data["status"] = Submission.Status.PROCESSING

    with transaction.atomic():
        # Lock both parents: an archive committed during validation must
        # reject the upload rather than creating work behind the archive.
        assessment = lock_active_assessment(validated_data["assessment"].pk)
        validated_data["assessment"] = assessment
        submission = Submission.objects.create(**validated_data)
        SubmissionAudit.objects.create(
            submission=submission,
            actor=actor,
            previous_status=None,
            new_status=submission.status,
            reason="Submission uploaded for recognition",
        )
        enqueue_recognition(submission)

    return submission


def replace_submission(instance, validated_data, actor):

    if instance.qr_group_key:
        raise ValidationError(
            "Upload additional QR pages through the assessment upload endpoint; use page review to correct grouping."
        )
    validated_data = dict(validated_data)
    incoming_version = validated_data.get("version")
    if incoming_version is None:
        raise ValidationError({"version": "This field is required on update."})
    with transaction.atomic():
        lock_submission_scope(instance.pk)
        # Recognition workers lock their job before updating the submission.
        # Use that same order before cancellation, avoiding a lock cycle.
        list(
            RecognitionJob.objects.filter(
                submission=instance,
                status__in=RecognitionJob.ACTIVE_STATUSES,
            )
            .select_for_update()
            .values_list("pk", flat=True)
        )
        locked = get_object_or_404(
            Submission.objects.active()
            .select_related("assessment__course")
            .select_for_update(of=("self",)),
            pk=instance.pk,
        )
        if incoming_version != locked.version:
            raise ValidationError(
                {"version": "This submission has changed. Reload and try again."}
            )
        if (
            "assessment" in validated_data
            and validated_data["assessment"].pk != locked.assessment_id
        ):
            raise ValidationError(
                {"assessment": "A submission cannot be moved to another assessment."}
            )
        if (
            "enrollment" in validated_data
            and getattr(validated_data["enrollment"], "pk", None)
            != locked.enrollment_id
        ):
            raise ValidationError(
                {"enrollment": "Use verification to change the student."}
            )
        validated_data.pop("version", None)
        validated_data.pop("assessment", None)
        validated_data.pop("enrollment", None)
        if "file" not in validated_data:
            raise ValidationError(
                "Use verification for student changes or replace the file."
            )
        old_storage, old_name = locked.file.storage, locked.file.name
        validated_data.update(
            original_filename=validated_data["file"].name,
        )
        cancel_active_jobs(locked)
        supersede_submission_emails(locked)
        locked.record_status_change(
            actor=actor,
            new_status=Submission.Status.PROCESSING,
            new_enrollment=None,
            reason="Submission file replaced",
            expected_version=incoming_version,
        )
        for name, value in validated_data.items():
            setattr(locked, name, value)
        locked.save()
        enqueue_recognition(locked)
        if old_name and old_name != locked.file.name:
            delete_file_after_commit(old_storage, old_name, f"submission {locked.pk}")
    return locked
