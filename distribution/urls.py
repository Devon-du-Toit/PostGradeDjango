from django.urls import path

from distribution.views import (
    AssessmentScriptEmailApproveView,
    AssessmentScriptEmailListView,
    ScriptEmailApproveView,
    ScriptEmailDetailView,
    ScriptEmailRetryView,
    SubmissionScriptEmailView,
)

urlpatterns = [
    path(
        "submissions/<int:pk>/email/",
        SubmissionScriptEmailView.as_view(),
        name="submission-script-email",
    ),
    path(
        "assessments/<int:assessment_id>/script-emails/",
        AssessmentScriptEmailListView.as_view(),
        name="assessment-script-email-list",
    ),
    path(
        "assessments/<int:assessment_id>/script-emails/approve/",
        AssessmentScriptEmailApproveView.as_view(),
        name="assessment-script-email-approve",
    ),
    path(
        "script-emails/<int:pk>/",
        ScriptEmailDetailView.as_view(),
        name="script-email-detail",
    ),
    path(
        "script-emails/<int:pk>/approve/",
        ScriptEmailApproveView.as_view(),
        name="script-email-approve",
    ),
    path(
        "script-emails/<int:pk>/retry/",
        ScriptEmailRetryView.as_view(),
        name="script-email-retry",
    ),
]
