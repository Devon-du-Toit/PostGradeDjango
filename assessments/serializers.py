from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from assessments.models import Assessment
from courses.lifecycle import lock_active_course


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
            "expected_qr_page_labels",
            "qr_test",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "course",
            "created_at",
            "updated_at",
        ]

    def validate_expected_qr_page_labels(self, value):
        from submissions.qr import label_order

        if not isinstance(value, list) or len(value) > 20:
            raise serializers.ValidationError("Use a list of at most 20 page labels.")
        if any(not isinstance(label, str) for label in value):
            raise serializers.ValidationError("Page labels must be strings such as P1.")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Page labels must be unique.")
        try:
            return sorted(value, key=label_order)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Use labels such as P1 and P3.")

    def create(self, validated_data):
        with transaction.atomic():
            course = lock_active_course(
                validated_data["course"].pk,
                owner=self.context["request"].user,
            )
            return super().create({**validated_data, "course": course})

    def update(self, instance, validated_data):
        with transaction.atomic():
            lock_active_course(
                instance.course_id,
                owner=self.context["request"].user,
            )
            current = get_object_or_404(
                Assessment.objects.active().select_for_update(of=("self",)),
                pk=instance.pk,
                course_id=instance.course_id,
            )
            if current.submissions.filter(qr_group_key__gt="").exists() and any(
                key in validated_data and validated_data[key] != getattr(current, key)
                for key in ("expected_qr_page_labels", "qr_test", "date")
            ):
                raise serializers.ValidationError(
                    "QR configuration cannot change after QR intake."
                )
            return super().update(current, validated_data)
