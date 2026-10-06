from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from submissions.filters import (
    SUBMISSION_SEARCH_FIELDS,
    VERIFICATION_QUEUE_STATUSES,
    SubmissionFilter,
    VerificationQueueFilter,
)
from submissions.models import Submission
from submissions.serializers import SubmissionSerializer

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404

from students.models import Enrollment
from submissions.jobs import retry_recognition
from submissions.verification import verify_submission


class RecognitionMethodsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "methods": [
                    {"value": value, "label": label}
                    for value, label in Submission.RecognitionMethod.choices
                ],
                "bubble_templates": ["nwu-eight-standard-1", "nwu-eight-compact-1"],
            }
        )


class SubmissionListCreateView(generics.ListCreateAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = SubmissionFilter
    search_fields = SUBMISSION_SEARCH_FIELDS

    def get_queryset(self):
        return (
            Submission.objects.active()
            .filter(
                assessment__course__owner=self.request.user,
            )
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
            )
            .order_by("-created_at", "-id")
        )

    def perform_create(self, serializer):
        serializer.save()


class SubmissionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Submission.objects.active()
            .filter(
                assessment__course__owner=self.request.user,
            )
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
            )
        )


class SubmissionVerifyView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.active().filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        enrollment_id = request.data.get("enrollment")

        if enrollment_id is None:
            return Response(
                {"detail": "Enrollment is required."},
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
                actor=request.user,
            )
        except ValidationError as exc:
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


class SubmissionVerificationQueueView(generics.ListAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = VerificationQueueFilter
    search_fields = SUBMISSION_SEARCH_FIELDS

    def get_queryset(self):
        return (
            Submission.objects.active()
            .filter(
                assessment__course__owner=self.request.user,
                status__in=VERIFICATION_QUEUE_STATUSES,
            )
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
            )
            .order_by("created_at", "id")
        )


class SubmissionRecognitionImageView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.active().filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        attempt = submission.recognition_attempts.first()

        if attempt is None or not attempt.region_image:
            raise Http404("No recognition image for this submission.")

        return FileResponse(
            attempt.region_image.open("rb"),
            content_type="image/png",
        )


class SubmissionRetryRecognitionView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.active().filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        try:
            submission = retry_recognition(
                submission.pk,
            )
        except ValidationError as exc:
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
            status=status.HTTP_202_ACCEPTED,
        )


class SubmissionFileDownloadView(generics.GenericAPIView):
    """
    Serves the original uploaded submission file.

    Deliberately does NOT expose a raw MEDIA_URL path anywhere in
    the API: the only way to reach the file's bytes is through
    this endpoint, which enforces the same course-owner check used
    everywhere else in this app. Requesting another lecturer's
    submission id here returns 404, matching the existing pattern
    (e.g. SubmissionVerifyView) of not confirming another user's
    object exists at all.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.active().filter(
            assessment__course__owner=self.request.user,
        )

    def get(self, request, pk):
        submission = generics.get_object_or_404(
            self.get_queryset(),
            pk=pk,
        )

        if not submission.file:
            raise Http404

        try:
            file_handle = submission.file.open("rb")
        except (FileNotFoundError, OSError):
            raise Http404

        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=(submission.original_filename or submission.file.name),
        )
