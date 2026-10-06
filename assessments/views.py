import logging

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assessments.export import build_script_archive
from assessments.models import Assessment
from assessments.serializers import AssessmentSerializer
from courses.models import Course

logger = logging.getLogger(__name__)


class AssessmentScriptExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        assessment = get_object_or_404(
            Assessment.objects.active(), pk=pk, course__owner=request.user
        )
        try:
            archive = build_script_archive(assessment.submissions.all())
        except OSError:
            logger.exception("Could not build script archive for assessment %s", pk)
            return Response(
                {"detail": "Script export failed. Please try again later."}, status=503
            )
        if archive is None:
            return Response(
                {"detail": "This assessment has no uploaded scripts."}, status=404
            )
        response = FileResponse(
            archive,
            as_attachment=True,
            filename=f"assessment-{pk}-scripts.zip",
            content_type="application/zip",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CourseAssessmentListCreateView(generics.ListCreateAPIView):
    serializer_class = AssessmentSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["name"]

    def get_course(self):
        return get_object_or_404(
            Course,
            pk=self.kwargs["course_id"],
            owner=self.request.user,
            archived_at__isnull=True,
        )

    def get_queryset(self):
        course = self.get_course()
        return Assessment.objects.filter(
            course=course,
            archived_at__isnull=True,
        ).order_by("date", "name", "id")

    def perform_create(self, serializer):
        serializer.save(course=self.get_course())


class AssessmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AssessmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Assessment.objects.filter(
            course__owner=self.request.user,
            course__archived_at__isnull=True,
            archived_at__isnull=True,
        )

    def perform_destroy(self, instance):
        # Assessments are archived, never hard-deleted, so delivery history,
        # submissions and audit trails are kept.
        instance.archive()
