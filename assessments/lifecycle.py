from rest_framework import status
from rest_framework.response import Response

from assessments.models import Result
from submissions.models import Submission


def count_dependent_records(*, assessment=None, course=None):
    """Count the Results and Submissions that deleting this object would destroy."""
    if assessment is not None:
        results = Result.objects.filter(assessment=assessment)
        submissions = Submission.objects.filter(assessment=assessment)
    else:
        results = Result.objects.filter(assessment__course=course)
        submissions = Submission.objects.filter(assessment__course=course)

    return {
        "results": results.count(),
        "submissions": submissions.count(),
    }


def deletion_blocked_response(label, counts):
    """Return a 409 response if there is data to protect, otherwise None."""
    if counts["results"] == 0 and counts["submissions"] == 0:
        return None

    return Response(
        {
            "detail": (
                f"This {label} cannot be deleted because it has recorded "
                "results or submissions. Remove them first."
            ),
            **counts,
        },
        status=status.HTTP_409_CONFLICT,
    )