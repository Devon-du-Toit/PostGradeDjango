from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assessments.models import Assessment
from distribution.filters import ScriptEmailFilter
from distribution.models import ScriptEmail
from distribution.serializers import ScriptEmailSerializer
from distribution.services import (
    approve_assessment_emails,
    approve_email,
    retry_email,
    schedule_script_email,
)
from submissions.models import Submission


def owned_emails(user):
    return ScriptEmail.objects.filter(
        submission__assessment__course__owner=user,
        submission__assessment__archived_at__isnull=True,
        submission__assessment__course__archived_at__isnull=True,
    ).select_related(
        "submission",
        "enrollment__student",
    )


class SubmissionScriptEmailView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        submission = get_object_or_404(
            Submission.objects.active(), pk=pk, assessment__course__owner=request.user
        )
        try:
            email = schedule_script_email(submission)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            ScriptEmailSerializer(email).data, status=status.HTTP_202_ACCEPTED
        )


class AssessmentScriptEmailListView(generics.ListAPIView):
    serializer_class = ScriptEmailSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = ScriptEmailFilter
    search_fields = [
        "enrollment__student__student_number",
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "recipient",
    ]

    def get_queryset(self):
        assessment = get_object_or_404(
            Assessment.objects.active(),
            pk=self.kwargs["assessment_id"],
            course__owner=self.request.user,
        )

        return (
            owned_emails(self.request.user)
            .filter(
                submission__assessment=assessment,
            )
            .order_by("-created_at", "-id")
        )


class ScriptEmailDetailView(generics.RetrieveAPIView):
    serializer_class = ScriptEmailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return owned_emails(self.request.user)


class ScriptEmailApproveView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        email = get_object_or_404(
            owned_emails(request.user),
            pk=pk,
        )

        try:
            email = approve_email(email.pk, request.user)
        except ValidationError as exc:
            return Response(
                {
                    "detail": exc.message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ScriptEmailSerializer(email).data,
            status=status.HTTP_202_ACCEPTED,
        )


class AssessmentScriptEmailApproveView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, assessment_id):
        assessment = get_object_or_404(
            Assessment.objects.active(),
            pk=assessment_id,
            course__owner=request.user,
        )

        try:
            approved = approve_assessment_emails(assessment, request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "approved": approved,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ScriptEmailRetryView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        email = get_object_or_404(
            owned_emails(request.user),
            pk=pk,
        )

        try:
            email = retry_email(
                email.pk,
                confirm_duplicate=request.data.get("confirm_duplicate", False) is True,
            )
        except ValidationError as exc:
            return Response(
                {
                    "detail": exc.message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ScriptEmailSerializer(email).data,
            status=status.HTTP_202_ACCEPTED,
        )
