from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from courses.models import Course
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
