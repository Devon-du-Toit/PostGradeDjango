from rest_framework import serializers

from assessments.models import Assessment, Result


class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assessment
        fields = [
            "id",
            "course",
            "name",
            "max_mark",
            "weight",
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


class ResultSerializer(serializers.ModelSerializer):
    percentage = serializers.SerializerMethodField()

    student_number = serializers.CharField(
        source="enrollment.student.student_number",
        read_only=True,
    )

    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Result
        fields = [
            "id",
            "assessment",
            "enrollment",
            "student_number",
            "student_name",
            "mark",
            "percentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "assessment",
            "student_number",
            "student_name",
            "percentage",
            "created_at",
            "updated_at",
        ]

    def get_percentage(self, obj):
        return round(
            (obj.mark / obj.assessment.max_mark) * 100,
            2,
        )

    def get_student_name(self, obj):
        return (
            f"{obj.enrollment.student.first_name} "
            f"{obj.enrollment.student.last_name}"
        ).strip()

    def validate(self, attrs):
        assessment = self.context["assessment"]

        enrollment = attrs.get(
            "enrollment",
            getattr(self.instance, "enrollment", None),
        )

        mark = attrs.get(
            "mark",
            getattr(self.instance, "mark", None),
        )

        if enrollment.course_id != assessment.course_id:
            raise serializers.ValidationError(
                {
                    "enrollment": (
                        "Enrollment must belong to the same course "
                        "as the assessment."
                    )
                }
            )

        if (
            self.instance is None
            and Result.objects.filter(
                assessment=assessment,
                enrollment=enrollment,
            ).exists()
        ):
            raise serializers.ValidationError(
                {
                    "enrollment": (
                        "A result already exists for this enrollment "
                        "and assessment."
                    )
                }
            )

        if mark > assessment.max_mark:
            raise serializers.ValidationError(
                {
                    "mark": (
                        "Mark cannot exceed the assessment's maximum mark."
                    )
                }
            )

        return attrs