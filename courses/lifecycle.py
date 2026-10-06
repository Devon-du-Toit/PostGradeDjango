from django.shortcuts import get_object_or_404
from django.utils import timezone

from courses.models import Course


def stop_archived_work(**submission_scope):
    """Retain records, but prevent queued work for an archived parent.

    Called within the archive transaction. A running recognition worker's
    fencing check discards its result after cancellation. SMTP already in
    progress is not recalled; its delivery outcome remains recorded.
    """
    from distribution.models import ScriptEmail
    from submissions.models import RecognitionJob

    now = timezone.now()
    RecognitionJob.objects.filter(
        **{f"submission__{key}": value for key, value in submission_scope.items()},
        status__in=RecognitionJob.ACTIVE_STATUSES,
    ).update(
        status=RecognitionJob.Status.CANCELLED,
        lease_expires_at=None,
        finished_at=now,
        updated_at=now,
    )
    ScriptEmail.objects.filter(
        **{f"submission__{key}": value for key, value in submission_scope.items()},
        status__in=ScriptEmail.UNSENT_STATUSES,
    ).update(
        status=ScriptEmail.Status.SUPERSEDED,
        lease_expires_at=None,
        updated_at=now,
    )


def lock_active_course(course_id, owner=None):
    """Inside atomic(): acquire the course before child rows.

    Optional owner scoping preserves internal workflow calls that already
    resolved ownership, as well as serializer writes that must recheck it.
    """
    queryset = Course.objects.active().select_for_update()
    if owner is not None:
        queryset = queryset.filter(owner=owner)
    return get_object_or_404(queryset, pk=course_id)
