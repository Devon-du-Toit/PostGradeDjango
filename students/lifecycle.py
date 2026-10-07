from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from students.models import Enrollment, Student
from submissions.models import Submission
from submissions.retention import lock_submission_work, record_retention


def withdraw_enrollment(enrollment_id, actor, version, reason, *, restore=False):
    from django.shortcuts import get_object_or_404

    from courses.lifecycle import lock_active_course

    with transaction.atomic():
        scope = get_object_or_404(
            Enrollment.objects,
            pk=enrollment_id,
            course__owner=actor,
            student__owner=actor,
        )
        lock_active_course(scope.course_id, owner=actor)
        scripts = lock_submission_work(
            Submission.objects.filter(enrollment=scope).values_list("pk", flat=True)
        )
        student = Student.objects.select_for_update().get(pk=scope.student_id)
        current = Enrollment.objects.select_for_update().get(pk=scope.pk)
        if (
            type(version) is not int
            or current.version != version
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValidationError(
                "Withdrawal/restore requires the current version and a reason."
            )
        if restore and student.archived_at:
            raise ValidationError(
                "Restore the student contact before restoring class membership."
            )
        desired = None if restore else timezone.now()
        if (restore and current.withdrawn_at is None) or (
            not restore and current.withdrawn_at is not None
        ):
            return current
        current.withdrawn_at, current.withdrawal_reason = desired, reason.strip()
        current.version += 1
        # Parents/student already locked; no nested save reorders work locks.
        Enrollment.objects.filter(pk=current.pk).update(
            withdrawn_at=current.withdrawn_at,
            withdrawal_reason=current.withdrawal_reason,
            version=current.version,
        )
        for script in scripts:
            record_retention(
                script,
                actor,
                (
                    "Class membership restored: "
                    if restore
                    else "Class membership withdrawn: "
                )
                + reason.strip(),
            )
        return current


def archive_student(student_id, actor, version, reason, *, restore=False):
    from django.shortcuts import get_object_or_404

    from courses.models import Course

    with transaction.atomic():
        scope = get_object_or_404(Student.objects, pk=student_id, owner=actor)
        course_ids = list(scope.enrollments.values_list("course_id", flat=True))
        list(
            Course.objects.filter(pk__in=course_ids).order_by("pk").select_for_update()
        )
        current = Student.objects.select_for_update().get(pk=scope.pk)
        actual_course_ids = set(current.enrollments.values_list("course_id", flat=True))
        if not actual_course_ids.issubset(set(course_ids)):
            from rest_framework.exceptions import APIException

            class MembershipScopeChanged(APIException):
                status_code = 409
                default_detail = (
                    "Class memberships changed during archive. Reload and try again."
                )

            raise MembershipScopeChanged()
        scripts = lock_submission_work(
            Submission.objects.filter(enrollment__student=current).values_list(
                "pk", flat=True
            )
        )
        enrollments = list(current.enrollments.select_for_update().order_by("pk"))
        if (
            type(version) is not int
            or current.version != version
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValidationError(
                "Student archive/restore requires the current version and a reason."
            )
        if (
            restore
            and current.archived_at is None
            or not restore
            and current.archived_at is not None
        ):
            return current
        current.archived_at = None if restore else timezone.now()
        current.version += 1
        current.save(update_fields=["archived_at", "version", "updated_at"])
        if not restore:
            for enrollment in enrollments:
                if enrollment.withdrawn_at is None:
                    Enrollment.objects.filter(pk=enrollment.pk).update(
                        withdrawn_at=timezone.now(),
                        withdrawal_reason=reason.strip(),
                        version=enrollment.version + 1,
                    )
        for script in scripts:
            record_retention(
                script,
                actor,
                (
                    "Student contact restored: "
                    if restore
                    else "Student contact archived: "
                )
                + reason.strip(),
            )
        return current
