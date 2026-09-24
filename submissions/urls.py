from django.urls import path

from submissions.views import (
    SubmissionDetailView,
    SubmissionListCreateView,
    SubmissionMarkView,
    SubmissionRecognitionImageView,
    SubmissionRetryRecognitionView,
    SubmissionVerifyView,
    SubmissionVerificationQueueView,
)


urlpatterns = [
    path(
        "",
        SubmissionListCreateView.as_view(),
        name="submission-list-create",
    ),
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
        "<int:pk>/recognition-image/",
        SubmissionRecognitionImageView.as_view(),
        name="submission-recognition-image",
    ),
    path(
        "<int:pk>/retry-recognition/",
        SubmissionRetryRecognitionView.as_view(),
        name="submission-retry-recognition",
    ),
]