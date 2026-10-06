from django.db import models, transaction
from django.utils import timezone

from courses.models import Course


class AssessmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True, course__archived_at__isnull=True)


class Assessment(models.Model):
    objects = AssessmentQuerySet.as_manager()
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="assessments",
    )
    name = models.CharField(max_length=255)
    expected_qr_page_labels = models.JSONField(default=list, blank=True)
    qr_test = models.CharField(max_length=80, blank=True)

    date = models.DateField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["date", "name"]

    def __str__(self):
        return f"{self.course} - {self.name}"

    def archive(self):
        from courses.lifecycle import stop_archived_work

        with transaction.atomic():
            if self.archived_at is None:
                self.archived_at = timezone.now()
                self.save(update_fields=["archived_at", "updated_at"])
            stop_archived_work(assessment_id=self.pk)
