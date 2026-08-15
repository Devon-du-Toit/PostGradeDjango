import csv
import io

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from courses.models import Course
from students.models import Enrollment, Student
from students.serializers import EnrollmentSerializer, StudentSerializer
from django.db import transaction


class StudentListCreateView(generics.ListCreateAPIView):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Student.objects.filter(owner=self.request.user)

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

    def get_queryset(self):
        return Enrollment.objects.filter(
            course__owner=self.request.user,
            student__owner=self.request.user,
        )


class CourseStudentListView(generics.ListAPIView):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Student.objects.filter(
            owner=self.request.user,
            enrollments__course_id=self.kwargs["course_id"],
            enrollments__course__owner=self.request.user,
        )


class StudentCSVImportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, course_id):
        course = get_object_or_404(
            Course,
            id=course_id,
            owner=request.user,
        )

        uploaded_file = request.FILES.get("file")

        if uploaded_file is None:
            return Response(
                {"file": "A CSV file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        decoded_file = uploaded_file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(decoded_file))

        required_columns = {
            "student_number",
            "first_name",
            "last_name",
            "email",
        }

        missing_columns = required_columns - set(reader.fieldnames or [])

        if missing_columns:
            return Response(
                {
                    "file": (
                            "Missing required columns: "
                            + ", ".join(sorted(missing_columns))
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            for row_number, row in enumerate(reader, start=2):
                existing_student = Student.objects.filter(
                    owner=request.user,
                    student_number=row["student_number"],
                ).first()

                if existing_student:
                    student = existing_student
                else:
                    serializer = StudentSerializer(
                        data={
                            "student_number": row["student_number"],
                            "first_name": row["first_name"],
                            "last_name": row["last_name"],
                            "email": row["email"],
                        }
                    )

                    if not serializer.is_valid():
                        transaction.set_rollback(True)

                        return Response(
                            {
                                "row": row_number,
                                "errors": serializer.errors,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    student = serializer.save(owner=request.user)

                Enrollment.objects.get_or_create(
                    course=course,
                    student=student,
                )

        return Response(
            {"message": "Students imported successfully."},
            status=status.HTTP_200_OK,
        )