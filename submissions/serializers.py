import logging

from django.urls import reverse

from rest_framework import serializers

from submissions.models import Submission

from submissions.recognition.service import (
    recognize_submission,
)

from submissions.validation import (
    SubmissionFileValidationError,
    validate_submission_file,
)

logger = logging.getLogger(__name__)

class SubmissionSerializer(serializers.ModelSerializer):
    # "file" is accepted on upload but deliberately never rendered
    # back out (see extra_kwargs below): a raw MEDIA_URL path would
    # be guessable and unauthenticated. Callers instead get
    # "download_url", which always points at the authenticated,
    # course-owner-checked download endpoint.
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = [
            "id",
            "assessment",
            "enrollment",
            "file",
            "download_url",
            "original_filename",
            "status",
            "created_at",
            "updated_at",
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

    def validate_file(self, value):
        try:
            validate_submission_file(value)
        except SubmissionFileValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))

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

        submission = super().create(
            validated_data
        )

        try:
            enrollment = recognize_submission(
                submission
            )
        except Exception:
            logger.exception(
                "Automatic submission recognition failed for submission %s",
                submission.id,
            )
            enrollment = None

        if enrollment is not None:
            submission.enrollment = enrollment
            submission.status = Submission.Status.MATCHED
        else:
            submission.status = (
                Submission.Status.NEEDS_VERIFICATION
            )

        submission.save(
            update_fields=[
                "enrollment",
                "status",
            ]
        )

        return submission

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        if instance.enrollment is not None:
            instance.status = Submission.Status.MATCHED
        else:
            instance.status = Submission.Status.UPLOADED

        instance.save(update_fields=["status"])

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

        return attrs