import django_filters

from assessments.filters import owned_assessments
from config.filters import ChoiceInFilter
from courses.filters import owned_courses
from submissions.models import Submission


# Statuses listed in the verification queue; the dashboard's
# pending_verifications count uses the same set.
VERIFICATION_QUEUE_STATUSES = [
    Submission.Status.NEEDS_VERIFICATION,
    Submission.Status.MATCHED,
]

# Unmatched submissions have no student yet, so the filename is searched too.
SUBMISSION_SEARCH_FIELDS = [
    "original_filename",
    "enrollment__student__student_number",
    "enrollment__student__first_name",
    "enrollment__student__last_name",
]


class SubmissionFilter(django_filters.FilterSet):
    course = django_filters.ModelChoiceFilter(
        field_name="assessment__course",
        queryset=owned_courses,
    )
    assessment = django_filters.ModelChoiceFilter(queryset=owned_assessments)
    status = ChoiceInFilter(choices=Submission.Status.choices)

    class Meta:
        model = Submission
        fields = ["course", "assessment", "status"]


class VerificationQueueFilter(SubmissionFilter):
    # Only the queue's own statuses can be selected.
    status = ChoiceInFilter(
        choices=[
            (status.value, status.label)
            for status in VERIFICATION_QUEUE_STATUSES
        ],
    )
