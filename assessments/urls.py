from django.urls import path

from assessments.views import (
    AssessmentDetailView,
    AssessmentResultListCreateView,
    CourseAssessmentListCreateView,
    ResultDetailView,
)

urlpatterns = [
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
    path(
        "assessments/<int:assessment_id>/results/",
        AssessmentResultListCreateView.as_view(),
        name="assessment-result-list-create",
    ),
    path(
        "results/<int:pk>/",
        ResultDetailView.as_view(),
        name="result-detail",
    ),
]