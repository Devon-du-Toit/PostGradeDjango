from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from assessments.models import Assessment
from assessments.serializers import AssessmentSerializer
from courses.models import Course


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
