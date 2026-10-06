import json
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Q
from students.models import Enrollment
from submissions.models import Submission
from distribution.models import ScriptEmail


class Command(BaseCommand):
    help = (
        "Read-only report of domain membership violations and lifecycle review items."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fail-on-invalid", action="store_true")

    def handle(self, *args, **options):
        report = {
            "invalid_enrollment_owners": Enrollment.objects.exclude(
                student__owner_id=F("course__owner_id")
            ).count(),
            "invalid_submission_scopes": Submission.objects.filter(
                enrollment__isnull=False
            )
            .exclude(
                enrollment__course_id=F("assessment__course_id"),
                enrollment__student__owner_id=F("assessment__course__owner_id"),
            )
            .count(),
            "verified_without_enrollment": Submission.objects.filter(
                status="verified", enrollment__isnull=True
            ).count(),
            "duplicate_submission_groups": Submission.objects.filter(
                enrollment__isnull=False
            )
            .values("assessment_id", "enrollment_id")
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .count(),
            "unsent_orphan_deliveries": ScriptEmail.objects.filter(
                status__in=ScriptEmail.UNSENT_STATUSES
            )
            .filter(Q(submission__isnull=True) | Q(enrollment__isnull=True))
            .count(),
        }
        self.stdout.write(json.dumps(report, sort_keys=True))
        if options["fail_on_invalid"] and (
            report["invalid_enrollment_owners"] or report["invalid_submission_scopes"]
        ):
            raise CommandError(
                "Invalid membership records found; inspect before release. Nothing was changed."
            )
