from rest_framework import serializers

from assessments.models import Assessment


class AssessmentSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        retired = set(data) & {"max_mark", "weight", "mark"}
        if retired:
            raise serializers.ValidationError(
                {field: "Numeric grading is no longer supported." for field in retired}
            )
        return super().to_internal_value(data)

    class Meta:
        model = Assessment
        fields = [
            "id",
            "course",
            "name",
            "date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "course",
            "created_at",
            "updated_at",
        ]
