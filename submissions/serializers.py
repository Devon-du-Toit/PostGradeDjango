from django.db import transaction
from django.urls import reverse
from rest_framework import serializers

from submissions.jobs import (
    cancel_active_jobs,
    enqueue_recognition,
)
from submissions.models import (
    RecognitionAttempt,
    RecognitionJob,
    Submission,
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
            "raw_text",
            "raw_candidate",
            "suggested_enrollment",
            "suggested_student_number",
            "confidence",
            "confidence_type",
            "column_ambiguity",
            "region",
            "region_image_url",
            "quality_issues",
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
    recognition = serializers.SerializerMethodField()
    recognition_job = serializers.SerializerMethodField()
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
            "recognition_job",
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
        
    def validate_file(self, file):
        if (
            self.instance is not None
            and self.instance.status == Submission.Status.MARKED
        ):
            raise serializers.ValidationError(
                "The file of a marked submission cannot be replaced."
            )

        return file

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
            submission = super().create(
                validated_data
            )
            enqueue_recognition(submission)

        return submission

    def update(self, instance, validated_data):
        if "file" in validated_data:
            return self.replace_file(instance, validated_data)

        instance = super().update(instance, validated_data)

        if instance.enrollment is not None:
            instance.status = Submission.Status.MATCHED
        else:
            instance.status = Submission.Status.UPLOADED

        instance.save(update_fields=["status"])

        return instance

    def replace_file(self, instance, validated_data):
        # A new file invalidates any match made from the old one.
        validated_data["original_filename"] = validated_data["file"].name
        validated_data["enrollment"] = None
        validated_data["status"] = Submission.Status.PROCESSING

        with transaction.atomic():
            cancel_active_jobs(instance)
            instance = super().update(instance, validated_data)
            enqueue_recognition(instance)

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