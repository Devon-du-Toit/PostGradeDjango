from django.shortcuts import get_object_or_404

from assessments.models import Assessment
from courses.lifecycle import lock_active_course
from submissions.models import Submission


def lock_active_assessment(assessment_id):
    """Inside atomic(): lock course, then assessment, before child rows.

    All submission writes use this order. In particular, replacement must
    acquire parent locks before recognition-job locks, and job locks before
    the submission, to avoid cycles with archive and recognition workers.
    """
    assessment = get_object_or_404(Assessment.objects.active(), pk=assessment_id)
    lock_active_course(assessment.course_id)
    return get_object_or_404(
        Assessment.objects.active().select_for_update(), pk=assessment_id
    )


def lock_submission_scope(submission_id):
    submission = get_object_or_404(Submission.objects.active(), pk=submission_id)
    return lock_active_assessment(submission.assessment_id)
