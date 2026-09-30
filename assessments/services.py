from decimal import Decimal

from django.db.models import Count

from .models import Assessment


def calculate_course_grade(enrollment):
    results = enrollment.results.select_related("assessment").all()

    weighted_total = Decimal("0.00")
    completed_weight = Decimal("0.00")

    for result in results:
        assessment = result.assessment

        percentage = (
            result.mark / assessment.max_mark
        ) * Decimal("100.00")

        weighted_total += percentage * assessment.weight
        completed_weight += assessment.weight

    if completed_weight == 0:
        return Decimal("0.00")

    return (weighted_total / completed_weight).quantize(
        Decimal("0.01")
    )

def calculate_assessment_statistics(assessment):
    results = assessment.results.all()

    if not results.exists():
        return {
            "graded_count": 0,
            "average_percentage": Decimal("0.00"),
            "minimum_percentage": Decimal("0.00"),
            "maximum_percentage": Decimal("0.00"),
        }

    percentages = [
        (
            result.mark / assessment.max_mark
        ) * Decimal("100.00")
        for result in results
    ]

    return {
        "graded_count": len(percentages),
        "average_percentage": (
            sum(percentages) / len(percentages)
        ).quantize(Decimal("0.01")),
        "minimum_percentage": min(percentages).quantize(
            Decimal("0.01")
        ),
        "maximum_percentage": max(percentages).quantize(
            Decimal("0.01")
        ),
    }
def assessment_progress(user, course_id=None):
    queryset = Assessment.objects.filter(course__owner=user)
    if course_id is not None:
        queryset = queryset.filter(course_id=course_id)

    queryset = queryset.annotate(
        enrolled_count=Count("course__enrollments", distinct=True),
        marked_count=Count("results", distinct=True),
    ).order_by("course_id", "id")

    rows = []
    for assessment in queryset:
        remaining = max(assessment.enrolled_count - assessment.marked_count, 0)
        percent = (
            round(100 * assessment.marked_count / assessment.enrolled_count, 1)
            if assessment.enrolled_count else 0.0
        )
        rows.append({
            "assessment_id": assessment.id,
            "course_id": assessment.course_id,
            "name": assessment.name,
            "enrolled_count": assessment.enrolled_count,
            "marked_count": assessment.marked_count,
            "remaining_count": remaining,
            "percent_complete": percent,
        })
    return rows