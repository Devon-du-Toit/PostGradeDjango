from django.urls import path
from assessments.views import AssessmentDetailView, CourseAssessmentListCreateView

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
]
