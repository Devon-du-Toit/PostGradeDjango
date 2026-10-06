from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from assessments.models import Assessment
from courses.models import Course


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

    def create(self, validated_data):
        with transaction.atomic():
            course = get_object_or_404(
                Course.objects.active().select_for_update(),
                pk=validated_data["course"].pk,
                owner=self.context["request"].user,
            )
            return super().create({**validated_data, "course": course})

    def update(self, instance, validated_data):
        with transaction.atomic():
            get_object_or_404(
                Course.objects.active().select_for_update(),
                pk=instance.course_id,
                owner=self.context["request"].user,
            )
            current = get_object_or_404(
                Assessment.objects.active().select_for_update(of=("self",)),
                pk=instance.pk,
                course_id=instance.course_id,
            )
            return super().update(current, validated_data)
