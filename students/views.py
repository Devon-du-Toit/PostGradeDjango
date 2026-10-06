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
from students.serializers import (
    CSVImportOptionsSerializer,
    EnrollmentSerializer,
    StudentSerializer,
)
from submissions.emailing import send_student_email


class StudentEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        student = get_object_or_404(
            Student.objects.active(),
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
        return (
            Student.objects.active()
            .filter(
                owner=self.request.user,
            )
            .order_by("student_number", "id")
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    def perform_destroy(self, instance):
        from students.lifecycle import archive_student

        try:
            archive_student(
                instance.pk,
                self.request.user,
                self.request.data.get("version"),
                self.request.data.get("reason", ""),
            )
        except Exception as exc:
            from django.core.exceptions import ValidationError
            from rest_framework.exceptions import ValidationError as APIValidationError

            if isinstance(exc, ValidationError):
                raise APIValidationError(exc.messages) from exc
            raise

    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Student.objects.active().filter(owner=self.request.user)


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
        queryset = (
            Enrollment.objects.filter(
                course__owner=self.request.user,
                course__archived_at__isnull=True,
                student__owner=self.request.user,
            )
            .select_related("student")
            .order_by("course_id", "student__student_number", "id")
        )
        if self.request.query_params.get("include_withdrawn") != "true":
            queryset = queryset.filter(
                withdrawn_at__isnull=True, student__archived_at__isnull=True
            )
        return queryset


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
        return (
            Student.objects.active()
            .filter(
                owner=self.request.user,
                enrollments__course=course,
                enrollments__withdrawn_at__isnull=True,
            )
            .order_by("student_number", "id")
        )


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

        options = CSVImportOptionsSerializer(data=request.data)
        options.is_valid(raise_exception=True)
        dry_run = options.validated_data["dry_run"]
        update_existing = options.validated_data["update_existing"]

        try:
            plan = build_import_plan(
                request.user,
                uploaded_file,
                update_existing=update_existing,
                course=course,
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
                    {
                        "detail": exc.detail,
                        **({"errors": exc.errors} if exc.errors else {}),
                    },
                    status=exc.status_code,
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


class EnrollmentDetailView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    restore = False

    def mutate(self, request, pk):
        from django.core.exceptions import ValidationError
        from rest_framework.exceptions import ValidationError as APIValidationError

        from students.lifecycle import withdraw_enrollment

        try:
            enrollment = withdraw_enrollment(
                pk,
                request.user,
                request.data.get("version"),
                request.data.get("reason", ""),
                restore=self.restore,
            )
        except ValidationError as exc:
            raise APIValidationError(exc.messages) from exc
        return Response(
            EnrollmentSerializer(enrollment, context={"request": request}).data
        )

    def delete(self, request, pk):
        return self.mutate(request, pk)


class EnrollmentRestoreView(EnrollmentDetailView):
    restore = True
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        return self.mutate(request, pk)


class StudentRestoreView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from django.core.exceptions import ValidationError
        from rest_framework.exceptions import ValidationError as APIValidationError

        from students.lifecycle import archive_student

        try:
            student = archive_student(
                pk,
                request.user,
                request.data.get("version"),
                request.data.get("reason", ""),
                restore=True,
            )
        except ValidationError as exc:
            raise APIValidationError(exc.messages) from exc
        return Response(StudentSerializer(student, context={"request": request}).data)
