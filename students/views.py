from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from courses.models import Course
from students.csv_import import (
    CSVFileError,
    apply_import_plan,
    build_import_plan,
)
from students.filters import EnrollmentFilter, StudentFilter
from students.models import Enrollment, Student
from students.serializers import EnrollmentSerializer, StudentSerializer
from submissions.emailing import send_student_email


class StudentEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        student = get_object_or_404(
            Student,
            pk=pk,
            owner=request.user,
        )

        subject = request.data.get("subject", "").strip()
        message = request.data.get("message", "").strip()

        if not subject:
            return Response(
                {"detail": "Subject is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not message:
            return Response(
                {"detail": "Message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            send_student_email(
                student,
                subject=subject,
                message=message,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"detail": "Email sent."},
            status=status.HTTP_200_OK,
        )


class StudentListCreateView(generics.ListCreateAPIView):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = StudentFilter
    search_fields = ["student_number", "first_name", "last_name", "email"]

    def get_queryset(self):
        return Student.objects.filter(
            owner=self.request.user,
        ).order_by("student_number", "id")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Student.objects.filter(owner=self.request.user)


class EnrollmentListCreateView(generics.ListCreateAPIView):
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = EnrollmentFilter
    search_fields = [
        "student__student_number",
        "student__first_name",
        "student__last_name",
    ]

    def get_queryset(self):
        return Enrollment.objects.filter(
            course__owner=self.request.user,
            course__archived_at__isnull=True,
            student__owner=self.request.user,
        ).order_by("course_id", "student__student_number", "id")


class CourseStudentListView(generics.ListAPIView):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["student_number", "first_name", "last_name", "email"]

    def get_queryset(self):
        # Archived and other lecturers' courses behave like missing ones.
        course = get_object_or_404(
            Course.objects.active(),
            pk=self.kwargs["course_id"],
            owner=self.request.user,
        )
        return Student.objects.filter(
            owner=self.request.user,
            enrollments__course=course,
        ).order_by("student_number", "id")


def _flag(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class StudentCSVImportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, course_id):
        course = get_object_or_404(
            Course.objects.active(),
            id=course_id,
            owner=request.user,
        )

        uploaded_file = request.FILES.get("file")

        if uploaded_file is None:
            return Response(
                {"file": "A CSV file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dry_run = _flag(request.data.get("dry_run", False))
        update_existing = _flag(request.data.get("update_existing", False))

        try:
            plan = build_import_plan(
                request.user,
                uploaded_file,
                update_existing=update_existing,
                serializer_context={"request": request},
            )
        except CSVFileError as exc:
            return Response(
                {"file": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not plan.is_valid:
            return Response(
                {
                    "message": "Import failed. Nothing was saved.",
                    "errors": plan.errors,
                    "summary": plan.summary(),
                    "mismatches": plan.mismatches_payload(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not dry_run:
            try:
                apply_import_plan(request.user, course, plan)
            except CSVFileError as exc:
                return Response(
                    {"detail": exc.detail}, status=status.HTTP_404_NOT_FOUND,
                )

        return Response(
            {
                "message": (
                    "Dry run complete. Nothing was saved."
                    if dry_run
                    else "Students imported successfully."
                ),
                "dry_run": dry_run,
                "summary": plan.summary(),
                "mismatches": plan.mismatches_payload(),
            },
            status=status.HTTP_200_OK,
        )
