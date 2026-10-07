from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from students.models import Enrollment
from submissions.filters import (
    SUBMISSION_SEARCH_FIELDS,
    VERIFICATION_QUEUE_STATUSES,
    SubmissionFilter,
    VerificationQueueFilter,
)
from submissions.jobs import retry_recognition
from submissions.models import Submission
from submissions.serializers import (
    SubmissionRetrySerializer,
    SubmissionSerializer,
    SubmissionTransitionSerializer,
)
from submissions.verification import verify_submission


def protected_file_response(*args, **kwargs):
    from django.utils.cache import patch_vary_headers

    response = FileResponse(*args, **kwargs)
    response["Cache-Control"] = "private, no-store"
    patch_vary_headers(response, ["Authorization"])
    return response


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
            .select_related("assessment", "enrollment__student")
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
                "pages",
            )
            .order_by("-created_at", "-id")
        )

    def perform_create(self, serializer):
        serializer.save()


class SubmissionDetailView(generics.RetrieveUpdateDestroyAPIView):
    def perform_destroy(self, instance):
        from rest_framework.exceptions import ValidationError as APIValidationError

        from students.serializers import lifecycle_action
        from submissions.retention import archive_submission

        version, reason = lifecycle_action(self.request.data)
        try:
            archive_submission(instance, self.request.user, version, reason)
        except ValidationError as exc:
            raise APIValidationError(exc.messages) from exc

    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Submission.objects.active()
            .filter(
                assessment__course__owner=self.request.user,
            )
            .select_related("assessment", "enrollment__student")
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
                "pages",
            )
        )


class SubmissionVerifyView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    correction = False

    def post(self, request, pk):
        submission = generics.get_object_or_404(
            Submission.objects.active().filter(
                assessment__course__owner=request.user,
            ),
            pk=pk,
        )

        payload = SubmissionTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        enrollment_id = payload.validated_data["enrollment"]

        enrollment = generics.get_object_or_404(
            Enrollment.objects.active().filter(
                course__owner=request.user,
            ),
            pk=enrollment_id,
        )

        try:
            verify_submission(
                submission,
                enrollment,
                actor=request.user,
                expected_version=payload.validated_data.get("version"),
                correction=self.correction,
                reason=payload.validated_data.get("reason", ""),
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


class SubmissionCorrectionView(SubmissionVerifyView):
    correction = True


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
            .select_related("assessment", "enrollment__student")
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
                "pages",
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

        return protected_file_response(
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
            payload = SubmissionRetrySerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            submission = retry_recognition(
                submission.pk,
                actor=request.user,
                expected_version=payload.validated_data.get("version"),
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
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
            assessment__archived_at__isnull=True,
            assessment__course__archived_at__isnull=True,
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

        return protected_file_response(
            file_handle,
            as_attachment=True,
            filename=(submission.original_filename or submission.file.name),
        )


class ScriptPageFileView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, page_id):
        from submissions.models import ScriptPage

        page = generics.get_object_or_404(
            ScriptPage.objects.filter(
                submission__in=Submission.objects.filter(
                    assessment__archived_at__isnull=True,
                    assessment__course__archived_at__isnull=True,
                    assessment__course__owner=request.user,
                )
            ),
            submission_id=pk,
            pk=page_id,
        )
        try:
            return protected_file_response(
                page.file.open("rb"), content_type="application/pdf"
            )
        except OSError:
            raise Http404


class ScriptPageReviewView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, page_id):
        from submissions.qr import review_page

        try:
            submission = review_page(pk, page_id, request.data, request.user)
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError as APIValidationError

            raise APIValidationError(str(exc)) from exc
        return Response(
            SubmissionSerializer(submission, context={"request": request}).data
        )


class ScriptUploadFileView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, upload_id):
        from submissions.models import ScriptUpload

        upload = generics.get_object_or_404(
            ScriptUpload.objects.filter(
                assessment__in=Submission.objects.filter(
                    assessment__archived_at__isnull=True,
                    assessment__course__archived_at__isnull=True,
                )
                .filter(pk=pk, assessment__course__owner=request.user)
                .values("assessment_id"),
                pages__submission_id=pk,
            ).distinct(),
            pk=upload_id,
        )
        try:
            return protected_file_response(
                upload.file.open("rb"),
                as_attachment=True,
                filename="source-upload"
                + upload.file.name[upload.file.name.rfind(".") :],
            )
        except OSError:
            raise Http404


class SubmissionHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    filterset_class = SubmissionFilter

    def get_serializer_class(self):
        from submissions.serializers import SubmissionHistorySerializer

        return SubmissionHistorySerializer

    def get_queryset(self):
        from submissions.models import SubmissionAudit

        return (
            Submission.objects.filter(
                assessment__course__owner=self.request.user,
                assessment__archived_at__isnull=True,
                assessment__course__archived_at__isnull=True,
            )
            .select_related("assessment", "enrollment__student")
            .prefetch_related(
                "recognition_attempts",
                "recognition_jobs",
                "pages",
                "file_revisions",
                Prefetch(
                    "audit_entries",
                    queryset=SubmissionAudit.objects.select_related("actor"),
                ),
            )
            .order_by("-created_at", "-pk")
        )


class SubmissionHistoryFileView(SubmissionFileDownloadView):
    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
            assessment__archived_at__isnull=True,
            assessment__course__archived_at__isnull=True,
        )


class SubmissionRevisionFileView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, revision_id):
        from submissions.models import SubmissionFileRevision

        revision = generics.get_object_or_404(
            SubmissionFileRevision.objects.filter(
                submission__assessment__course__owner=request.user,
                submission__assessment__archived_at__isnull=True,
                submission__assessment__course__archived_at__isnull=True,
            ),
            pk=revision_id,
            submission_id=pk,
        )
        try:
            return protected_file_response(
                revision.file.open("rb"),
                as_attachment=True,
                filename=revision.original_filename,
            )
        except OSError:
            raise Http404
