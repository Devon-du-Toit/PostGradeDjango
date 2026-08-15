from django.urls import path

from submissions.views import (
    SubmissionDetailView,
    SubmissionListCreateView,
    SubmissionMarkView,
)


urlpatterns = [
    path(
        "",
        SubmissionListCreateView.as_view(),
        name="submission-list-create",
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
]