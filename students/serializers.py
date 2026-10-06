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
