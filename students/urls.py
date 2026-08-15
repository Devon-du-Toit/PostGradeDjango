from django.urls import path

from students.views import (
    EnrollmentListCreateView,
    StudentDetailView,
    StudentListCreateView,
)

urlpatterns = [
    path("", StudentListCreateView.as_view(), name="student-list-create"),
    path("<int:pk>/", StudentDetailView.as_view(), name="student-detail"),
    path(
        "enrollments/",
        EnrollmentListCreateView.as_view(),
        name="enrollment-list-create",
    ),
]