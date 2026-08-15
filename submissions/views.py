from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assessments.models import Result
from assessments.serializers import ResultSerializer
from submissions.models import Submission
from submissions.serializers import SubmissionSerializer


class SubmissionListCreateView(generics.ListCreateAPIView):
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Submission.objects.filter(
            assessment__course__owner=self.request.user,
        )

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

        if submission.enrollment is None:
            return Response(
                {
                    "detail": (
                        "Submission must be matched to a student "
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

        return Response(
            ResultSerializer(result).data,
            status=(
                status.HTTP_200_OK
                if existing_result
                else status.HTTP_201_CREATED
            ),
        )