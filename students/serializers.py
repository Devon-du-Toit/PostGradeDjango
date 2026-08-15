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


class EnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enrollment
        fields = [
            "id",
            "course",
            "student",
            "created_at",
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