import django_filters

from courses.filters import owned_courses
from students.models import Enrollment, Student


def owned_students(request):
    if request is None:
        return Student.objects.none()
    return Student.objects.filter(owner=request.user)


class StudentFilter(django_filters.FilterSet):
    # ?course=<id>: students enrolled in that course
    course = django_filters.ModelChoiceFilter(
        field_name="enrollments__course",
        queryset=owned_courses,
    )

    class Meta:
        model = Student
        fields = ["course"]


class EnrollmentFilter(django_filters.FilterSet):
    course = django_filters.ModelChoiceFilter(queryset=owned_courses)
    student = django_filters.ModelChoiceFilter(queryset=owned_students)

    class Meta:
        model = Enrollment
        fields = ["course", "student"]
