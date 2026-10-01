import django_filters

from config.filters import ChoiceInFilter
from distribution.models import ResultEmail


class ResultEmailFilter(django_filters.FilterSet):
    status = ChoiceInFilter(choices=ResultEmail.Status.choices)

    class Meta:
        model = ResultEmail
        fields = ["status"]
