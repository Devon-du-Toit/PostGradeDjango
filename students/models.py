from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class StudentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True)


class Student(models.Model):
    objects = StudentQuerySet.as_manager()
    archived_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
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

    def save(self, *args, **kwargs):
        if self.pk:
            with transaction.atomic():
                current = Student.objects.select_for_update().filter(pk=self.pk).first()
                if (
                    current
                    and current.owner_id != self.owner_id
                    and self.enrollments.exists()
                ):
                    raise ValidationError(
                        "Cannot transfer a student while course enrollments exist."
                    )
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student_number} - {self.first_name} {self.last_name}"


class EnrollmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            withdrawn_at__isnull=True,
            student__archived_at__isnull=True,
            course__archived_at__isnull=True,
        )


class Enrollment(models.Model):
    objects = EnrollmentQuerySet.as_manager()
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=0)

    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
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
            raise ValidationError("Student and course must belong to the same owner.")

    def save(self, *args, **kwargs):
        from courses.models import Course

        with transaction.atomic():
            self.course = Course.objects.select_for_update().get(pk=self.course_id)
            self.student = Student.objects.select_for_update().get(pk=self.student_id)
            self.clean()
            if not self.pk and (self.student.archived_at or self.course.archived_at):
                raise ValidationError(
                    "Restore archived contacts/courses before enrolling."
                )
            if self.pk:
                previous = (
                    Enrollment.objects.select_for_update().filter(pk=self.pk).first()
                )
                if (
                    previous
                    and (previous.course_id, previous.student_id)
                    != (self.course_id, self.student_id)
                    and self.submissions.exists()
                ):
                    raise ValidationError(
                        "A referenced enrollment cannot be reassigned."
                    )
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} enrolled in {self.course}"
