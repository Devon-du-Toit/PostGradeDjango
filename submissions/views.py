from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assessments.models import Result
from assessments.serializers import ResultSerializer
from distribution.serializers import ResultEmailSerializer
from distribution.services import schedule_result_email
from submissions.models import Submission, SubmissionAudit
from submissions.serializers import SubmissionSerializer

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404

from students.models import Enrollment
from submissions.jobs import retry_recognition
from submissions.verification import verify_submission


class SubmissionListCreateView(generics.ListCreateAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        ).prefetch_related(
            "recognition_attempts",
            "recognition_jobs",
        )

    def perform_create(self, serializer):
        serializer.save()

class SubmissionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        ).prefetch_related(
            "recognition_attempts",
            "recognition_jobs",
        )

class SubmissionMarkView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        # Mark, status and email record commit together: a mail problem
        # can never undo or lose a saved mark.
        with transaction.atomic():
            # Locked so a repeated request waits, then sees "marked".
            submission = generics.get_object_or_404(
                Submission.objects.select_for_update().filter(
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

            existing_result = Result.objects.select_for_update().filter(
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

            previous_status = submission.status
            submission.status = Submission.Status.MARKED
            submission.save(update_fields=["status"])

            SubmissionAudit.objects.create(
                submission=submission,
                actor=request.user,
                previous_status=previous_status,
                new_status=Submission.Status.MARKED,
                previous_enrollment=submission.enrollment,
                new_enrollment=submission.enrollment,
                reason="Result created",
            )

            email = schedule_result_email(result)

        return Response(
            {
                **ResultSerializer(result).data,
                "email_delivery": ResultEmailSerializer(email).data,
            },
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
        ).prefetch_related(
            "recognition_attempts",
            "recognition_jobs",
        ).order_by("created_at")

class SubmissionRecognitionImageView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        attempt = submission.recognition_attempts.first()

        if attempt is None or not attempt.region_image:
            raise Http404(
                "No recognition image for this submission."
            )

        return FileResponse(
            attempt.region_image.open("rb"),
            content_type="image/png",
        )


class SubmissionRetryRecognitionView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.filter(
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
    (e.g. SubmissionMarkView) of not confirming another user's
    object exists at all.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
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
            filename=(
                submission.original_filename
                or submission.file.name
            ),
        )
