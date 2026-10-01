from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from courses.models import Course
from courses.serializers import CourseSerializer

from assessments.lifecycle import (
    count_dependent_records,
    deletion_blocked_response,
)

class CourseListCreateView(generics.ListCreateAPIView):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]

    # user only gets their own courses
    def get_queryset(self):
        return Course.objects.filter(owner=self.request.user)

    # course ownership comes from the authenticated user
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CourseDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Course.objects.filter(owner=self.request.user)

    def destroy(self, request, *args, **kwargs):
        course = self.get_object()
        blocked = deletion_blocked_response(
            "course",
            count_dependent_records(course=course),
        )
        if blocked is not None:
            return blocked
        return super().destroy(request, *args, **kwargs)