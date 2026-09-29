from django.urls import path

from distribution.views import (
    AssessmentResultEmailApproveView,
    AssessmentResultEmailListView,
    ResultEmailApproveView,
    ResultEmailDetailView,
    ResultEmailRetryView,
)


urlpatterns = [
    path(
        "assessments/<int:assessment_id>/result-emails/",
        AssessmentResultEmailListView.as_view(),
        name="assessment-result-email-list",
    ),
    path(
        "assessments/<int:assessment_id>/result-emails/approve/",
        AssessmentResultEmailApproveView.as_view(),
        name="assessment-result-email-approve",
    ),
    path(
        "result-emails/<int:pk>/",
        ResultEmailDetailView.as_view(),
        name="result-email-detail",
    ),
    path(
        "result-emails/<int:pk>/approve/",
        ResultEmailApproveView.as_view(),
        name="result-email-approve",
    ),
    path(
        "result-emails/<int:pk>/retry/",
        ResultEmailRetryView.as_view(),
        name="result-email-retry",
    ),
]
