from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/courses/", include("courses.urls")),
    path("api/students/", include("students.urls")),
    path("api/enrollments/", include("students.enrollment_urls")),
    path("api/", include("assessments.urls")),
    path("api/submissions/", include("submissions.urls")),
]