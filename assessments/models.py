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