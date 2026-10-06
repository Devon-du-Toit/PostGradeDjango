from django.db import transaction
from django.urls import reverse
from rest_framework import serializers
from assessments.models import Assessment
from students.models import Enrollment

from submissions.jobs import (
    cancel_active_jobs,
    enqueue_recognition,
)
from submissions.models import (
    RecognitionAttempt,
    RecognitionJob,
    Submission,
)

from submissions.signals import delete_file_after_commit
from submissions.validation import (
    SubmissionFileValidationError,
    validate_submission_file,
)

class RecognitionAttemptSerializer(serializers.ModelSerializer):
    region_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = RecognitionAttempt
        fields = [
            "id",
            "method",
            "outcome",
            "processing_version",
            "template_version",
            "column_scores",
            "raw_text",
            "raw_candidate",
            "raw_candidates",
            "suggested_enrollment",
            "suggested_student_number",
            "confidence",
            "confidence_type",
            "column_ambiguity",
            "region",
            "region_image_url",
            "quality_issues",
            "error_type",
            "created_at",
        ]
        read_only_fields = fields

    def get_region_image_url(self, attempt):
        if not attempt.region_image:
            return None

        return reverse(
            "submission-recognition-image",
            kwargs={"pk": attempt.submission_id},
        )


class RecognitionJobSerializer(serializers.ModelSerializer):
    failure_reason = serializers.SerializerMethodField()

    class Meta:
        model = RecognitionJob
        fields = [
            "id",
            "status",
            "attempts",
            "max_attempts",
            "run_after",
            "failure_reason",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields

    def get_failure_reason(self, job):
        # Exception type only; the full text may contain server paths.
        if not job.last_error:
            return None

        return job.last_error.split(":", 1)[0]


class SubmissionSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assessment"].queryset = Assessment.objects.active()
        self.fields["enrollment"].queryset = Enrollment.objects.filter(
            course__archived_at__isnull=True,
        )

    recognition = serializers.SerializerMethodField()
    recognition_job = serializers.SerializerMethodField()
    # "file" is accepted on upload but never rendered back out (see
    # extra_kwargs): a raw MEDIA_URL path would be guessable and
    # unauthenticated. Clients use download_url, the owner-checked endpoint.
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = [
            "id",
            "assessment",
            "recognition_method",
            "enrollment",
            "file",
            "download_url",
            "original_filename",
            "status",
            "recognition",
            "recognition_job",
            "created_at",
            "updated_at",
            "version",
        ]
        read_only_fields = [
            "id",
            "original_filename",
            "status",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "file": {"write_only": True},
        }

    def get_download_url(self, submission):
        if not submission.file:
            return None

        request = self.context.get("request")
        path = reverse(
            "submission-file-download",
            args=[submission.id],
        )

        if request is not None:
            return request.build_absolute_uri(path)

        return path

    def validate_file(self, file):
        # Replacing a file is allowed until the submission is marked: a
        # recorded grade exists against the current file from then on.
        if (
            self.instance is not None
            and self.instance.status == Submission.Status.MARKED
        ):
            raise serializers.ValidationError(
                "The file of a marked submission cannot be replaced."
            )

        # Checks the real content (type, size, pages, dimensions) before
        # the file can reach the expensive recognition pipeline.
        try:
            validate_submission_file(file)
        except SubmissionFileValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))

        return file

    def get_recognition_job(self, submission):
        jobs = submission.recognition_jobs.all()

        if not jobs:
            return None

        return RecognitionJobSerializer(
            jobs[0],
        ).data

    def get_recognition(self, submission):
        attempts = submission.recognition_attempts.all()

        if not attempts:
            return None

        return RecognitionAttemptSerializer(
            attempts[0],
        ).data

    def validate_version(self, value):
        instance = self.instance
        if instance is None:
            return value
        if value != instance.version:
            raise serializers.ValidationError(
                "This submission has been updated since you read it. "
                "Reload and try again."
            )
        return value

    def validate_assessment(self, assessment):
        request = self.context["request"]

        if assessment.course.owner != request.user:
            raise serializers.ValidationError(
                "You cannot upload a submission for this assessment."
            )

        return assessment

    def create(self, validated_data):
        uploaded_file = validated_data["file"]
        validated_data["original_filename"] = uploaded_file.name
        validated_data["status"] = Submission.Status.PROCESSING

        with transaction.atomic():
            # Lock both parents: an archive committed during validation must
            # reject the upload rather than creating work behind the archive.
            try:
                assessment = (
                    Assessment.objects.active()
                    .select_related("course")
                    .select_for_update(of=("self", "course"))
                    .get(pk=validated_data["assessment"].pk)
                )
            except Assessment.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"assessment": "The assessment is archived or unavailable."}
                ) from exc
            validated_data["assessment"] = assessment
            submission = super().create(
                validated_data
            )
            enqueue_recognition(submission)

        return submission

    def update(self, instance, validated_data):
        if "file" in validated_data:
            return self.replace_file(instance, validated_data)

        # Status changes go through Submission.record_status_change()
        # so we do not silently reset status on generic edits.
        #
        # Require a version field on every update so a client working
        # from a stale read cannot write over newer data.
        incoming_version = self.initial_data.get("version")
        if incoming_version is None:
            raise serializers.ValidationError(
                {
                    "version": "This field is required on update."
                }
            )
        if int(incoming_version) != instance.version:
            raise serializers.ValidationError(
                {
                    "version": (
                        "This submission has been updated since you "
                        "read it. Reload and try again."
                    )
                }
            )

        instance = super().update(instance, validated_data)
        instance.version = instance.version + 1
        instance.save(update_fields=["version", "updated_at"])
        return instance

    def replace_file(self, instance, validated_data):
        # A new file invalidates any match made from the old one.
        old_storage = instance.file.storage
        old_name = instance.file.name

        validated_data["original_filename"] = validated_data["file"].name
        validated_data["enrollment"] = None
        validated_data["status"] = Submission.Status.PROCESSING

        with transaction.atomic():
            cancel_active_jobs(instance)
            instance = super().update(instance, validated_data)
            enqueue_recognition(instance)

            # The old file goes only once the new one is committed, so a
            # failed replacement never leaves the submission without a file.
            if old_name and old_name != instance.file.name:
                delete_file_after_commit(
                    old_storage,
                    old_name,
                    f"submission {instance.pk}",
                )

        return instance

    def validate_enrollment(self, enrollment):
        if enrollment is None:
            return enrollment

        request = self.context["request"]

        if enrollment.course.owner != request.user:
            raise serializers.ValidationError(
                "You cannot assign this enrollment."
            )

        return enrollment

    def validate(self, attrs):
        if (self.instance is not None and "recognition_method" in attrs
                and attrs["recognition_method"] != self.instance.recognition_method
                and "file" not in attrs):
            raise serializers.ValidationError({
                "recognition_method": "Replace the file to change its recognition method. Retries preserve the selected method.",
            })
        enrollment = attrs.get(
            "enrollment",
            getattr(self.instance, "enrollment", None),
        )

        assessment = attrs.get(
            "assessment",
            getattr(self.instance, "assessment", None),
        )

        if (
                enrollment is not None
                and assessment is not None
                and enrollment.course_id != assessment.course_id
        ):
            raise serializers.ValidationError(
                {
                    "enrollment": (
                        "Enrollment must belong to the same course "
                        "as the assessment."
                    )
                }
            )

        # A running recognition job would overwrite a manual choice made now,
        # because generic edits no longer move the status off "processing".
        if (
            self.instance is not None
            and "enrollment" in attrs
            and "file" not in attrs
            and self.instance.status == Submission.Status.PROCESSING
        ):
            raise serializers.ValidationError(
                {
                    "enrollment": (
                        "Recognition is still running. Wait for it to "
                        "finish, or use verify."
                    )
                }
            )

        return attrs
