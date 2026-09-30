from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assessments.models import Result
from assessments.serializers import ResultSerializer
from config.pagination import OptInPagination
from courses.models import Course
from students.models import Enrollment
from submissions.emailing import send_result_email
from submissions.models import Submission
from submissions.serializers import SubmissionSerializer
from submissions.verification import verify_submission
from .filters import StrictOrderingFilter, SubmissionFilter
from .mixins import StableOrderingMixin
from .summary import pending_verification_counts


class SubmissionListCreateView(StableOrderingMixin, generics.ListCreateAPIView):
    serializer_class = SubmissionSerializer
    pagination_class = OptInPagination
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, StrictOrderingFilter]
    filterset_class = SubmissionFilter
    search_fields = [
        "enrollment__student__student_number",
        "enrollment__student__first_name",
        "enrollment__student__last_name",
    ]
    ordering_fields = ["created_at", "updated_at", "status", "original_filename"]
    ordering = ["-created_at", "id"]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        ).select_related("assessment","enrollment","enrollment__student")

    def perform_create(self, serializer):
        serializer.save()

class SubmissionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        )

class SubmissionMarkView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        if submission.status != Submission.Status.VERIFIED:
            return Response(
                {
                    "detail": (
                        "Submission must be verified "
                        "before entering a mark."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_result = Result.objects.filter(
            assessment=submission.assessment,
            enrollment=submission.enrollment,
        ).first()

        serializer = ResultSerializer(
            existing_result,
            data={
                "enrollment": submission.enrollment_id,
                "mark": request.data.get("mark"),
            },
            context={
                "request": request,
                "assessment": submission.assessment,
            },
        )

        serializer.is_valid(raise_exception=True)
        result = serializer.save(
            assessment=submission.assessment,
        )

        submission.status = Submission.Status.MARKED
        submission.save(update_fields=["status"])
        send_result_email(result)

        return Response(
            ResultSerializer(result).data,
            status=(
                status.HTTP_200_OK
                if existing_result
                else status.HTTP_201_CREATED
            ),
        )


class SubmissionVerifyView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        enrollment_id = request.data.get("enrollment")

        if enrollment_id is None:
            return Response(
                {
                    "detail": "Enrollment is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = generics.get_object_or_404(
            Enrollment.objects.filter(
                course__owner=request.user,
            ),
            pk=enrollment_id,
        )

        try:
            verify_submission(
                submission,
                enrollment,
            )
        except DjangoValidationError as exc:
            return Response(
                {
                    "detail": exc.message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            SubmissionSerializer(
                submission,
                context={
                    "request": request,
                },
            ).data,
            status=status.HTTP_200_OK,
        )


class SubmissionVerificationQueueView(
    generics.ListAPIView
):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
            status__in=[
                Submission.Status.NEEDS_VERIFICATION,
                Submission.Status.MATCHED,
            ],
        ).order_by("created_at")

class SummaryQuerySerializer(serializers.Serializer):
    course = serializers.IntegerField(required=False, min_value=1)


class SubmissionSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = SummaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        course_id = query.validated_data.get("course")
        if course_id and not Course.objects.filter(pk=course_id, owner=request.user).exists():
            raise ValidationError({"course": ["Course not found."]})
        return Response(pending_verification_counts(request.user, course_id))