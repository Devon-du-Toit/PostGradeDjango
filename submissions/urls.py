from django.urls import path

from submissions.views import (
    SubmissionDetailView,
    SubmissionListCreateView,
    SubmissionMarkView,
    SubmissionVerifyView,
    SubmissionVerificationQueueView,
)
#what I added
from .summary import AssessmentProgressView
from .views import SubmissionSummaryView


urlpatterns = [
    path(
        "assessment-progress/",
        AssessmentProgressView.as_view(),
        name="assessment-progress",
    ),
    path("summary/", SubmissionSummaryView.as_view(), name="submission-summary"),
    path(
        "verification-queue/",
        SubmissionVerificationQueueView.as_view(),
        name="submission-verification-queue",
    ),
    path(
        "<int:pk>/",
        SubmissionDetailView.as_view(),
        name="submission-detail",
    ),
    path(
        "<int:pk>/mark/",
        SubmissionMarkView.as_view(),
        name="submission-mark",
    ),
    path(
        "<int:pk>/verify/",
        SubmissionVerifyView.as_view(),
        name="submission-verify",
    ),
    path(
            "",
            SubmissionListCreateView.as_view(),
            name="submission-list-create",
        ),
]