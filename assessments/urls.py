from django.urls import path

from assessments.views import (
    AssessmentDetailView,
    AssessmentScriptExportView,
    CourseAssessmentListCreateView,
)

urlpatterns = [
    path(
        "assessments/<int:pk>/scripts/export/",
        AssessmentScriptExportView.as_view(),
        name="assessment-script-export",
    ),
    path(
        "courses/<int:course_id>/assessments/",
        CourseAssessmentListCreateView.as_view(),
        name="course-assessment-list-create",
    ),
    path(
        "assessments/<int:pk>/",
        AssessmentDetailView.as_view(),
        name="assessment-detail",
    ),
]
