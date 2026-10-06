from rest_framework import serializers

from distribution.models import ScriptEmail


class ScriptEmailSerializer(serializers.ModelSerializer):
    student_number = serializers.CharField(
        source="enrollment.student.student_number",
        read_only=True,
    )

    is_current = serializers.SerializerMethodField()

    class Meta:
        model = ScriptEmail
        fields = [
            "id",
            "submission",
            "submission_version",
            "attachment_filename",
            "is_current",
            "student_number",
            "recipient",
            "subject",
            "body",
            "status",
            "failure_reason",
            "attempts",
            "max_attempts",
            "run_after",
            "approved_at",
            "sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_is_current(self, email):
        return (
            email.submission is not None
            and email.submission.status == "verified"
            and email.submission_version == email.submission.version
            and email.enrollment_id == email.submission.enrollment_id
        )
