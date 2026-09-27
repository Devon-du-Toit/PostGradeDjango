from rest_framework import serializers

from distribution.models import ResultEmail


class ResultEmailSerializer(serializers.ModelSerializer):
    student_number = serializers.CharField(
        source="result.enrollment.student.student_number",
        read_only=True,
    )

    is_current = serializers.SerializerMethodField()

    class Meta:
        model = ResultEmail
        fields = [
            "id",
            "result",
            "result_version",
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
        return email.result_version == email.result.version
