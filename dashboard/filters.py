import django_filters

from assessments.models import Assessment
from courses.filters import owned_courses


class AssessmentProgressFilter(django_filters.FilterSet):
    course = django_filters.ModelChoiceFilter(queryset=owned_courses)

    class Meta:
        model = Assessment
        fields = ["course"]
