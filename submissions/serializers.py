import logging

from rest_framework import serializers

from submissions.models import Submission

from submissions.recognition.service import (
    recognize_submission,
)

logger = logging.getLogger(__name__)

class SubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = [
            "id",
            "assessment",
            "enrollment",
            "file",
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
            submission.record_status_change(
                actor=None,
                new_status=Submission.Status.MATCHED,
                reason="Automatic recognition matched",
                new_enrollment=enrollment,
            )
        else:
            submission.record_status_change(
                actor=None,
                new_status=Submission.Status.NEEDS_VERIFICATION,
                reason="Automatic recognition could not match",
            )

        return submission

    def update(self, instance, validated_data):
        # Status changes go through Submission.record_status_change()
        # so we do not silently reset status on generic edits.
        return super().update(instance, validated_data)

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
