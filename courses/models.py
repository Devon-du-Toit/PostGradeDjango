from django.conf import settings
from django.db import models
from django.utils import timezone


class Course(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, # points to the custom email-based user model
        on_delete=models.CASCADE, # deleting user also deletes courses
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

    def __str__(self):
        return f"{self.code} - {self.name}"

    def archive(self):
        if self.archived_at is None:
            self.archived_at = timezone.now()
            self.save(update_fields=["archived_at", "updated_at"])