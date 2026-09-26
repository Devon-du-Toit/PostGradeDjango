from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assessments.models import Assessment
from distribution.models import ResultEmail
from distribution.serializers import ResultEmailSerializer
from distribution.services import (
    approve_assessment_emails,
    approve_email,
    retry_email,
)


def owned_emails(user):
    return ResultEmail.objects.filter(
        result__assessment__course__owner=user,
    ).select_related(
        "result__enrollment__student",
    )


class AssessmentResultEmailListView(generics.ListAPIView):
    serializer_class = ResultEmailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        assessment = get_object_or_404(
            Assessment,
            pk=self.kwargs["assessment_id"],
            course__owner=self.request.user,
        )

        return owned_emails(self.request.user).filter(
            result__assessment=assessment,
        )


class ResultEmailDetailView(generics.RetrieveAPIView):
    serializer_class = ResultEmailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return owned_emails(self.request.user)


class ResultEmailApproveView(generics.GenericAPIView):
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
            ResultEmailSerializer(email).data,
            status=status.HTTP_202_ACCEPTED,
        )


class AssessmentResultEmailApproveView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, assessment_id):
        assessment = get_object_or_404(
            Assessment,
            pk=assessment_id,
            course__owner=request.user,
        )

        approved = approve_assessment_emails(
            assessment,
            request.user,
        )

        return Response(
            {
                "approved": approved,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ResultEmailRetryView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        email = get_object_or_404(
            owned_emails(request.user),
            pk=pk,
        )

        try:
            email = retry_email(
                email.pk,
                confirm_duplicate=bool(
                    request.data.get("confirm_duplicate", False)
                ),
            )
        except ValidationError as exc:
            return Response(
                {
                    "detail": exc.message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ResultEmailSerializer(email).data,
            status=status.HTTP_202_ACCEPTED,
        )
