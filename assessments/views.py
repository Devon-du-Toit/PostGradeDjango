from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from decimal import Decimal

from assessments.models import Assessment, Result
from assessments.serializers import AssessmentSerializer, ResultSerializer
from assessments.services import (
    calculate_assessment_statistics,
    calculate_course_grade,
)
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


class CourseGradebookView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        course = get_object_or_404(
            Course,
            id=course_id,
            owner=request.user,
        )

        enrollments = course.enrollments.select_related(
            "student"
        ).all()

        students = []

        for enrollment in enrollments:
            assessments = course.assessments.all()

            assessment_data = []

            for assessment in assessments:
                result = enrollment.results.filter(
                    assessment=assessment
                ).first()

                assessment_data.append(
                    {
                        "assessment": assessment.id,
                        "name": assessment.name,
                        "mark": result.mark if result else None,
                        "max_mark": assessment.max_mark,
                        "percentage": (
                            (
                                    result.mark / assessment.max_mark
                            ) * Decimal("100.00")
                            if result
                            else None
                        ),
                        "weight": assessment.weight,
                    }
                )

            students.append(
                {
                    "enrollment": enrollment.id,
                    "student": enrollment.student.id,
                    "student_number": enrollment.student.student_number,
                    "first_name": enrollment.student.first_name,
                    "last_name": enrollment.student.last_name,
                    "assessments": assessment_data,
                    "course_percentage": calculate_course_grade(
                        enrollment
                    ),
                }
            )

        return Response(
            {
                "course": course.id,
                "students": students,
            }
        )


class AssessmentStatisticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        assessment = get_object_or_404(
            Assessment,
            pk=pk,
            course__owner=request.user,
        )

        statistics = calculate_assessment_statistics(
            assessment
        )

        return Response(
            {
                "assessment": assessment.id,
                "name": assessment.name,
                **statistics,
            }
        )