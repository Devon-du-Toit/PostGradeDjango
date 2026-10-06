from django.urls import reverse
from rest_framework import serializers

from assessments.models import Assessment
from students.models import Enrollment
from submissions.models import RecognitionAttempt, RecognitionJob, Submission
from submissions.services import create_submission, replace_submission
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
        return create_submission(validated_data, actor=self.context["request"].user)

    def update(self, instance, validated_data):
        return replace_submission(
            instance, validated_data, actor=self.context["request"].user
        )

    def validate_enrollment(self, enrollment):
        if enrollment is None:
            return enrollment

        request = self.context["request"]

        if enrollment.course.owner != request.user:
            raise serializers.ValidationError("You cannot assign this enrollment.")

        return enrollment

    def validate(self, attrs):
        if (
            self.instance is not None
            and "recognition_method" in attrs
            and attrs["recognition_method"] != self.instance.recognition_method
            and "file" not in attrs
        ):
            raise serializers.ValidationError(
                {
                    "recognition_method": "Replace the file to change its recognition method. Retries preserve the selected method.",
                }
            )
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


class SubmissionTransitionSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField(min_value=1)
    version = serializers.IntegerField(min_value=0, required=False)
    reason = serializers.CharField(required=False, max_length=2000)


class SubmissionRetrySerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=0, required=False)
