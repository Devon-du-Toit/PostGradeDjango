from django.http import FileResponse, Http404

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assessments.models import Result
from assessments.serializers import ResultSerializer
from submissions.models import Submission
from submissions.serializers import SubmissionSerializer
from submissions.emailing import send_result_email

from django.core.exceptions import ValidationError

from students.models import Enrollment
from submissions.verification import verify_submission


class SubmissionListCreateView(generics.ListCreateAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        )

    def perform_create(self, serializer):
        serializer.save()

class SubmissionDetailView(generics.RetrieveUpdateDestroyAPIView):
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
        ).order_by("created_at")



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