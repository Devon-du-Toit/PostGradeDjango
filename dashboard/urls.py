from django.urls import path

from dashboard.views import DashboardAssessmentListView, DashboardStatsView

urlpatterns = [
    path(
        "stats/",
        DashboardStatsView.as_view(),
        name="dashboard-stats",
    ),
    path(
        "assessments/",
        DashboardAssessmentListView.as_view(),
        name="dashboard-assessments",
    ),
]
