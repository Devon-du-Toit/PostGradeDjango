import django_filters

from config.filters import ChoiceInFilter
from distribution.models import ScriptEmail


class ScriptEmailFilter(django_filters.FilterSet):
    status = ChoiceInFilter(choices=ScriptEmail.Status.choices)

    class Meta:
        model = ScriptEmail
        fields = ["status"]
