from rest_framework import serializers

from assessments.models import Assessment
from submissions.models import Submission


class AssessmentProgressSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    enrolled = serializers.IntegerField(source="enrolled_count", read_only=True)
    results_recorded = serializers.IntegerField(
        source="results_count",
        read_only=True,
    )
    submissions = serializers.SerializerMethodField()
    submissions_by_status = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id",
            "name",
            "date",
            "max_mark",
            "course",
            "course_code",
            "enrolled",
            "submissions",
            "submissions_by_status",
            "results_recorded",
        ]
        read_only_fields = fields

    def get_submissions_by_status(self, assessment):
        counts = self.context["status_counts"].get(assessment.id, {})
        return {
            status: counts.get(status, 0)
            for status in Submission.Status.values
        }

    def get_submissions(self, assessment):
        return sum(self.context["status_counts"].get(assessment.id, {}).values())
