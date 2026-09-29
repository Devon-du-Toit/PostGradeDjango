import logging

from rest_framework import serializers
from django.urls import reverse

from submissions.models import RecognitionAttempt, Submission

from submissions.recognition.service import (
    recognize_submission,
)

logger = logging.getLogger(__name__)

class RecognitionAttemptSerializer(serializers.ModelSerializer):
    region_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = RecognitionAttempt
        fields = [
            "id",
            "method",
            "outcome",
            "processing_version",
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

class SubmissionSerializer(serializers.ModelSerializer):
    recognition = serializers.SerializerMethodField()
    
    class Meta:
        model = Submission
        fields = [
            "id",
            "assessment",
            "enrollment",
            "file",
            "original_filename",
            "status",
            "recognition",
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

    def get_recognition(self, submission):
        attempts = submission.recognition_attempts.all()

        if not attempts:
            return None

        return RecognitionAttemptSerializer(
            attempts[0],
        ).data

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
