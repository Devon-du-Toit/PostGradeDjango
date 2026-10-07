from django.urls import path

from students.views import (
    EnrollmentDetailView,
    EnrollmentListCreateView,
    EnrollmentRestoreView,
)

urlpatterns = [
    path("<int:pk>/", EnrollmentDetailView.as_view(), name="enrollment-detail"),
    path(
        "<int:pk>/restore/", EnrollmentRestoreView.as_view(), name="enrollment-restore"
    ),
    path("", EnrollmentListCreateView.as_view(), name="enrollment-list-create"),
]
