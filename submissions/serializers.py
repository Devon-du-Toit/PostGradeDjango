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
        # Replacing a submission's file is allowed, except once it
        # has been marked - at that point a recorded grade exists
        # against the current file/enrollment, and swapping the
        # file out from under it would be misleading. This mirrors
        # PR #19's policy so the two PRs don't disagree.
        if (
            self.instance is not None
            and self.instance.status == Submission.Status.MARKED
        ):
            raise serializers.ValidationError(
                "The file of a marked submission cannot be replaced."
            )

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
            recognition_result = recognize_submission(
                submission
            )
        except Exception:
            logger.exception(
                "Automatic submission recognition failed for submission %s",
                submission.id,
            )
            recognition_result = None

        if (
            recognition_result is not None
            and recognition_result.enrollment is not None
        ):
            submission.enrollment = (
                recognition_result.enrollment
            )
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
        if "file" in validated_data:
            return self.replace_file(instance, validated_data)

        # Status changes go through Submission.record_status_change()
        # so we do not silently reset status on generic edits.
        return super().update(instance, validated_data)

    def replace_file(self, instance, validated_data):
        # A new file invalidates any match made from the old one,
        # so recognition runs again from scratch, same as create().
        # The old file is only deleted once the new one is safely
        # saved, so a failure here never leaves the submission with
        # no file at all.
        old_file = instance.file

        uploaded_file = validated_data["file"]
        validated_data["original_filename"] = uploaded_file.name
        validated_data["enrollment"] = None

        instance = super().update(instance, validated_data)

        try:
            recognition_result = recognize_submission(
                instance
            )
        except Exception:
            logger.exception(
                "Automatic submission recognition failed for submission %s",
                instance.id,
            )
            recognition_result = None

        if (
            recognition_result is not None
            and recognition_result.enrollment is not None
        ):
            instance.enrollment = (
                recognition_result.enrollment
            )
            instance.status = Submission.Status.MATCHED
        else:
            instance.status = (
                Submission.Status.NEEDS_VERIFICATION
            )

        instance.save(
            update_fields=[
                "enrollment",
                "status",
            ]
        )

        if old_file:
            old_file.storage.delete(old_file.name)

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
