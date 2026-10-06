from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from courses.models import Course
from students.models import Enrollment, Student


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "student_number",
            "first_name",
            "last_name",
            "email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

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
                    Student.objects.select_for_update(),
                    pk=instance.pk,
                    owner=self.context["request"].user,
                )
                return super().update(current, validated_data)
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"student_number": "Student records changed. Reload and try again."}
            ) from exc


class EnrollmentSerializer(serializers.ModelSerializer):
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
            "created_at",
            "student_number",
            "first_name",
            "last_name",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        course = attrs["course"]
        student = attrs["student"]

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
            course = get_object_or_404(
                Course.objects.active().select_for_update(),
                pk=validated_data["course"].pk,
                owner=self.context["request"].user,
            )
            student = get_object_or_404(
                Student.objects.select_for_update(),
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
