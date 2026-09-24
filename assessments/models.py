from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from courses.models import Course
from students.models import Enrollment


class Assessment(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="assessments",
    )
    name = models.CharField(max_length=255)

    max_mark = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01")),
        ],
    )

    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )

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

    class Meta:
        ordering = ["date", "name"]

    def __str__(self):
        return f"{self.course} - {self.name}"


class Result(models.Model):
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="results",
    )
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="results",
    )
    mark = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.00")),
        ],
    )

    # Incremented whenever the mark changes; result emails are tied to it.
    version = models.PositiveIntegerField(
        default=1,
        editable=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "enrollment"],
                name="unique_result_per_assessment_enrollment",
            ),
        ]

    @classmethod
    def from_db(cls, *args, **kwargs):
        instance = super().from_db(*args, **kwargs)
        instance._saved_mark = instance.mark
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._saved_mark = self.mark

    def save(self, *args, **kwargs):
        saved_mark = getattr(self, "_saved_mark", None)

        if (
            self.pk is not None
            and saved_mark is not None
            and self.mark != saved_mark
        ):
            self.version += 1

            update_fields = kwargs.get("update_fields")

            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "version"}

        super().save(*args, **kwargs)

        self._saved_mark = self.mark

    def clean(self):
        super().clean()

        if self.assessment_id and self.enrollment_id:
            if self.assessment.course_id != self.enrollment.course_id:
                raise ValidationError(
                    {
                        "enrollment": (
                            "Enrollment must belong to the same course "
                            "as the assessment."
                        )
                    }
                )

        if self.assessment_id and self.mark is not None:
            if self.mark > self.assessment.max_mark:
                raise ValidationError(
                    {
                        "mark": (
                            "Mark cannot exceed the assessment's maximum mark."
                        )
                    }
                )

    def __str__(self):
        return (
            f"{self.enrollment.student} - "
            f"{self.assessment.name}: {self.mark}"
        )