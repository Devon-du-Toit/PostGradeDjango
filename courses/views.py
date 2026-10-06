from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from courses.models import Course
from courses.serializers import CourseSerializer


class CourseListCreateView(generics.ListCreateAPIView):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["year", "semester"]
    search_fields = ["code", "name"]

    # user only gets their own courses, and archived ones are hidden
    def get_queryset(self):
        return Course.objects.filter(
            owner=self.request.user,
            archived_at__isnull=True,
        ).order_by("-year", "-semester", "code", "id")

    # course ownership comes from the authenticated user
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CourseDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Course.objects.filter(
            owner=self.request.user,
            archived_at__isnull=True,
        )

    def perform_destroy(self, instance):
        # Courses are archived, never hard-deleted, so delivery history,
        # submissions and audit trails are kept.
        instance.archive()
