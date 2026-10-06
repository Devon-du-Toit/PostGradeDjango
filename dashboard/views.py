from collections import defaultdict

from django.db.models import Count, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assessments.models import Assessment, Result
from courses.models import Course
from dashboard.filters import AssessmentProgressFilter
from dashboard.serializers import AssessmentProgressSerializer
from students.models import Enrollment
from submissions.filters import VERIFICATION_QUEUE_STATUSES
from submissions.models import Submission


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_courses = Course.objects.filter(
            owner=request.user,
            year=timezone.localdate().year,
        ).count()

        # One GROUP BY query; statuses with no submissions are filled with 0.
        counts = dict(
            Submission.objects.filter(
                assessment__course__owner=request.user,
            ).values_list("status").annotate(total=Count("id")).order_by()
        )
        by_status = {
            status: counts.get(status, 0)
            for status in Submission.Status.values
        }

        return Response(
            {
                "active_courses": active_courses,
                "pending_verifications": sum(
                    by_status[status] for status in VERIFICATION_QUEUE_STATUSES
                ),
                "submissions_by_status": by_status,
            }
        )


def count_of(queryset, link_field):
    # A correlated COUNT subquery per assessment row. Joining enrollments,
    # submissions and results in one query would multiply the rows
    # (students x scripts x marks) before counting.
    return Coalesce(
        Subquery(
            queryset.order_by()
            .values(link_field)
            .annotate(total=Count("pk"))
            .values("total"),
            output_field=IntegerField(),
        ),
        Value(0),
    )


def submission_status_counts(assessments):
    # One GROUP BY query for the whole page: {assessment_id: {status: n}}
    counts = defaultdict(dict)
    rows = Submission.objects.filter(
        assessment__in=assessments,
    ).values_list("assessment_id", "status").annotate(total=Count("id")).order_by()
    for assessment_id, status, total in rows:
        counts[assessment_id][status] = total
    return counts


class DashboardAssessmentListView(generics.ListAPIView):
    serializer_class = AssessmentProgressSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AssessmentProgressFilter
    search_fields = ["name", "course__code", "course__name"]

    def get_queryset(self):
        return Assessment.objects.filter(
            course__owner=self.request.user,
        ).select_related(
            "course",
        ).annotate(
            enrolled_count=count_of(
                Enrollment.objects.filter(course=OuterRef("course")),
                "course",
            ),
            results_count=count_of(
                Result.objects.filter(assessment=OuterRef("pk")),
                "assessment",
            ),
        ).order_by(F("date").desc(nulls_last=True), "-id")

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self.status_counts = submission_status_counts(page)
        return page

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["status_counts"] = getattr(self, "status_counts", {})
        return context
