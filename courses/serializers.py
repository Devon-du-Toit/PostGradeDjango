from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from courses.models import Course


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = [
            "id",
            "code",
            "name",
            "year",
            "semester",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        # The owner comes from the request, so DRF cannot enforce
        # unique_course_per_owner_period on its own; without this check a
        # duplicate reaches the database and the request fails with a 500.
        request = self.context["request"]
        period = {
            field: attrs.get(field, getattr(self.instance, field, None))
            for field in ("code", "year", "semester")
        }

        duplicates = Course.objects.filter(owner=request.user, **period)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError(
                {
                    "code": (
                        "You already have a course with this code "
                        "for that year and semester."
                    )
                }
            )

        return attrs

    def update(self, instance, validated_data):
        with transaction.atomic():
            current = get_object_or_404(
                Course.objects.active().select_for_update(),
                pk=instance.pk,
                owner=self.context["request"].user,
            )
            return super().update(current, validated_data)
