from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from courses.lifecycle import lock_active_course
from courses.models import Course
from students.models import Enrollment, Student


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "version",
            "archived_at",
            "student_number",
            "first_name",
            "last_name",
            "email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "version",
            "archived_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if self.instance is not None and self.instance.archived_at:
            raise serializers.ValidationError(
                "Restore the archived contact explicitly before editing or importing."
            )
        return attrs

    def validate_student_number(self, student_number):
        # The owner comes from the request, so DRF cannot enforce
        # unique_student_number_per_owner on its own; without this check a
        # duplicate reaches the database and the request fails with a 500.
        request = self.context["request"]

        duplicates = Student.objects.filter(
            owner=request.user,
            student_number=student_number,
        )
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError(
                "You already have a student with this student number."
            )

        return student_number

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"student_number": "Student records changed. Reload and try again."}
            ) from exc

    def update(self, instance, validated_data):
        try:
            with transaction.atomic():
                current = get_object_or_404(
                    Student.objects.active().select_for_update(),
                    pk=instance.pk,
                    owner=self.context["request"].user,
                )
                current.version += 1
                return super().update(current, validated_data)
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"student_number": "Student records changed. Reload and try again."}
            ) from exc


class EnrollmentSerializer(serializers.ModelSerializer):
    student_version = serializers.IntegerField(source="student.version", read_only=True)
    student_archived_at = serializers.DateTimeField(
        source="student.archived_at", read_only=True
    )
    student_number = serializers.CharField(
        source="student.student_number", read_only=True
    )
    first_name = serializers.CharField(source="student.first_name", read_only=True)
    last_name = serializers.CharField(source="student.last_name", read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.active()

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "course",
            "student",
            "student_version",
            "student_archived_at",
            "version",
            "withdrawn_at",
            "withdrawal_reason",
            "created_at",
            "student_number",
            "first_name",
            "last_name",
        ]
        read_only_fields = [
            "id",
            "version",
            "withdrawn_at",
            "withdrawal_reason",
            "created_at",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        course = attrs["course"]
        student = attrs["student"]
        if student.archived_at:
            raise serializers.ValidationError(
                "Restore the archived student before enrolling."
            )

        if course.owner != request.user:
            raise serializers.ValidationError(
                {"course": "You cannot enroll students in this course."}
            )

        if student.owner != request.user:
            raise serializers.ValidationError(
                {"student": "You cannot enroll this student."}
            )

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            course = lock_active_course(
                validated_data["course"].pk,
                owner=self.context["request"].user,
            )
            student = get_object_or_404(
                Student.objects.active().select_for_update(),
                pk=validated_data["student"].pk,
                owner=course.owner,
            )
            if Enrollment.objects.filter(course=course, student=student).exists():
                raise serializers.ValidationError("This student is already enrolled.")
            return super().create(
                {**validated_data, "course": course, "student": student}
            )


class CSVImportOptionsSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=False)
    update_existing = serializers.BooleanField(default=False)


class LifecycleActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(max_length=2000, trim_whitespace=True)

    def validate_version(self, value):
        if type(self.initial_data.get("version")) is not int:
            raise serializers.ValidationError(
                "Use the integer version returned by the API."
            )
        return value


def lifecycle_action(data):
    serializer = LifecycleActionSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["version"], serializer.validated_data["reason"]
