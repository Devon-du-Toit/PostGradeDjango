from django.urls import path

from students.views import (
    EnrollmentDetailView,
    EnrollmentListCreateView,
    EnrollmentRestoreView,
    StudentDetailView,
    StudentEmailView,
    StudentListCreateView,
    StudentRestoreView,
)

urlpatterns = [
    path("<int:pk>/restore/", StudentRestoreView.as_view(), name="student-restore"),
    path("enrollments/<int:pk>/", EnrollmentDetailView.as_view()),
    path("enrollments/<int:pk>/restore/", EnrollmentRestoreView.as_view()),
    path("", StudentListCreateView.as_view(), name="student-list-create"),
    path("<int:pk>/", StudentDetailView.as_view(), name="student-detail"),
    path(
        "enrollments/",
        EnrollmentListCreateView.as_view(),
        name="enrollment-list-create",
    ),
    path(
        "<int:pk>/email/",
        StudentEmailView.as_view(),
        name="student-email",
    ),
]
