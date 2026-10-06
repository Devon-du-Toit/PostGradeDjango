from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class CourseQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True)


class Course(models.Model):
    objects = CourseQuerySet.as_manager()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # points to the custom email-based user model
        on_delete=models.CASCADE,  # deleting user also deletes courses
        related_name="courses",
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    year = models.PositiveIntegerField()
    semester = models.PositiveSmallIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # database constraint to force uniqueness
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "code", "year", "semester"],
                name="unique_course_per_owner_period",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            with transaction.atomic():
                current = Course.objects.select_for_update().filter(pk=self.pk).first()
                if (
                    current
                    and current.owner_id != self.owner_id
                    and self.enrollments.exists()
                ):
                    raise ValidationError(
                        "Cannot transfer a course while enrollments exist."
                    )
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"

    def archive(self):
        from courses.lifecycle import stop_archived_work

        with transaction.atomic():
            if self.archived_at is None:
                self.archived_at = timezone.now()
                self.save(update_fields=["archived_at", "updated_at"])
            stop_archived_work(assessment__course_id=self.pk)
