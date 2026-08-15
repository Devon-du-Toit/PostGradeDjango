from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class Student(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="students",
    )
    student_number = models.CharField(max_length=50)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Uniqueness constraint on Student
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "student_number"],
                name="unique_student_number_per_owner",
            )
        ]

    def __str__(self):
        return f"{self.student_number} - {self.first_name} {self.last_name}"


class Enrollment(models.Model):
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student"],
                name="unique_student_enrollment",
            )
        ]

    def clean(self):
        if self.course.owner_id != self.student.owner_id:
            raise ValidationError(
                "Student and course must belong to the same owner."
            )

    def __str__(self):
        return f"{self.student} enrolled in {self.course}"