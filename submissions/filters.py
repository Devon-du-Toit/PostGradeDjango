import django_filters as filters
from django import forms
from rest_framework.filters import OrderingFilter
from rest_framework.exceptions import ValidationError
from assessments.models import Assessment
from courses.models import Course
from .models import Submission


class PositiveIntegerFilter(filters.NumberFilter):
    field_class = forms.IntegerField


class StrictOrderingFilter(OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = request.query_params.get(self.ordering_param)
        if ordering:
            allowed = getattr(view, 'ordering_fields', [])
            if isinstance(allowed, dict):
                allowed = list(allowed.keys())
            for field in ordering.split(','):
                clean = field[1:] if field.startswith('-') else field
                if not clean or clean not in allowed:
                    raise ValidationError({"ordering": f"Invalid ordering field: {field}"})
        return super().filter_queryset(request, queryset, view)

class SubmissionFilter(filters.FilterSet):
    course = PositiveIntegerFilter(method="filter_course", min_value=1)
    assessment = PositiveIntegerFilter(method="filter_assessment", min_value=1)
    status = filters.ChoiceFilter(choices=Submission.Status.choices)
    
    class Meta:
        model = Submission
        fields = ["course", "assessment", "status"]

    def filter_course(self, queryset, name, value):
        if not Course.objects.filter(pk=value, owner=self.request.user).exists():
            raise ValidationError({"course": "Invalid course id. Must be an owned course."})
        return queryset.filter(assessment__course_id=value)

    def filter_assessment(self, queryset, name, value):
        if not Assessment.objects.filter(pk=value, course__owner=self.request.user).exists():
            raise ValidationError({"assessment": "Invalid assessment id. Must be owned."})
        return queryset.filter(assessment_id=value)
        
