from django.urls import path

from courses.views import CourseDetailView, CourseListCreateView
from students.views import CourseStudentListView, StudentCSVImportView


urlpatterns = [
    path("", CourseListCreateView.as_view(), name="course-list-create"),
    path("<int:pk>/", CourseDetailView.as_view(), name="course-detail"),
    path(
        "<int:course_id>/students/",
        CourseStudentListView.as_view(),
        name="course-student-list",
    ),
    path(
        "<int:course_id>/import-students/",
        StudentCSVImportView.as_view(),
        name="student-csv-import",
    ),
]