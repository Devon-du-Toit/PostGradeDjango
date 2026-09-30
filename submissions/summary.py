from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from courses.models import Course
from.models import Submission

def pending_verification_counts(user, course_id=None):
    queryset = Submission.objects.filter(assessment__course__owner=user)

    if course_id is not None:
        if not Course.objects.filter(pk=course_id, owner=user).exists():
            raise ValidationError({"course": "Invalid course id. Must be an owned course."})

        queryset = queryset.filter(assessment__course_id=course_id)

    counts = queryset.aggregate(
        needs_verification=Count("id", filter=Q(status="needs_verification")),
        matched=Count("id", filter=Q(status="matched")),
    )
    counts["pending_verification"] = counts["needs_verification"] + counts["matched"]
    return counts

class AssessmentProgressView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get("course")
        if course_id not in (None, ""):
            try:
                course_id = int(course_id)
            except ValueError:
                raise ValidationError({"course": "Invalid course id. Must be integer."})
        else:
            course_id = None

        counts = pending_verification_counts(request.user, course_id=course_id)
        return Response(counts)