from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from assessments.models import Assessment, Result
from assessments.serializers import AssessmentSerializer, ResultSerializer
from courses.models import Course


class CourseAssessmentListCreateView(generics.ListCreateAPIView):
    serializer_class = AssessmentSerializer
    permission_classes = [IsAuthenticated]

    def get_course(self):
        return get_object_or_404(
            Course,
            pk=self.kwargs["course_id"],
            owner=self.request.user,
        )

    def get_queryset(self):
        course = self.get_course()
        return Assessment.objects.filter(course=course)

    def perform_create(self, serializer):
        serializer.save(course=self.get_course())


class AssessmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AssessmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Assessment.objects.filter(
            course__owner=self.request.user,
        )


class AssessmentResultListCreateView(generics.ListCreateAPIView):
    serializer_class = ResultSerializer
    permission_classes = [IsAuthenticated]

    def get_assessment(self):
        return get_object_or_404(
            Assessment,
            pk=self.kwargs["assessment_id"],
            course__owner=self.request.user,
        )

    def get_queryset(self):
        return Result.objects.filter(
            assessment=self.get_assessment(),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["assessment"] = self.get_assessment()
        return context

    def perform_create(self, serializer):
        serializer.save(
            assessment=self.get_assessment(),
        )


class ResultDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Result.objects.filter(
            assessment__course__owner=self.request.user,
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        result = self.get_object()
        context["assessment"] = result.assessment
        return context