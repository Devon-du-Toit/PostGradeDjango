"""Synthetic PostgreSQL migration, query and recovery evidence. Never a production loader."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient


def guard():
    name = connection.settings_dict["NAME"]
    media = Path(settings.MEDIA_ROOT).resolve()
    if (
        not settings.DEBUG
        or not name.startswith("postgrade_review_")
        or not media.name.startswith("postgrade_review_")
    ):
        raise RuntimeError(
            "Requires DEBUG and dedicated postgrade_review_ database/media names."
        )
    return media


def seed_legacy(media):
    if connection.introspection.table_names():
        raise RuntimeError(
            "Legacy seeding requires a completely empty scratch database."
        )
    before = [
        ("accounts", "0004_user_role"),
        ("courses", "0003_course_archived_at"),
        ("assessments", "0004_assessment_archived_at"),
        ("distribution", "0001_initial"),
        ("submissions", "0012_bubble_recognition_method_and_evidence"),
    ]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    apps = executor.loader.project_state(before).apps
    User = apps.get_model("accounts", "User")
    Course = apps.get_model("courses", "Course")
    Assessment = apps.get_model("assessments", "Assessment")
    Student = apps.get_model("students", "Student")
    Enrollment = apps.get_model("students", "Enrollment")
    Submission = apps.get_model("submissions", "Submission")
    Result = apps.get_model("assessments", "Result")
    Email = apps.get_model("distribution", "ResultEmail")
    Attempt = apps.get_model("submissions", "RecognitionAttempt")
    Job = apps.get_model("submissions", "RecognitionJob")
    Audit = apps.get_model("submissions", "SubmissionAudit")
    from django.utils import timezone
    from submissions.tests.helpers import make_pdf, make_png

    media.mkdir(parents=True, exist_ok=False)
    (media / "source.pdf").write_bytes(make_pdf())
    (media / "crop.png").write_bytes(make_png())
    owner = User.objects.create(email="review@example.invalid", password="!synthetic")
    active = Course.objects.create(
        owner_id=owner.pk, code="SYN101", name="Synthetic", year=2026, semester=1
    )
    archived = Course.objects.create(
        owner_id=owner.pk,
        code="SYN102",
        name="Archived",
        year=2026,
        semester=1,
        archived_at=timezone.now(),
    )
    assessment = Assessment.objects.create(
        course_id=active.pk, name="Legacy", max_mark=100, weight=10
    )
    old_assessment = Assessment.objects.create(
        course_id=archived.pk,
        name="Archived legacy",
        max_mark=100,
        weight=10,
        archived_at=timezone.now(),
    )
    students = Student.objects.bulk_create(
        [
            Student(
                owner_id=owner.pk,
                student_number=f"{i:08d}",
                first_name=f"Synthetic{i}",
                last_name="Fixture",
                email=f"student{i}@example.invalid",
            )
            for i in range(300)
        ]
    )
    enrolled = Enrollment.objects.bulk_create(
        [Enrollment(course_id=active.pk, student_id=s.pk) for s in students]
    )
    old_enrolled = Enrollment.objects.bulk_create(
        [Enrollment(course_id=archived.pk, student_id=s.pk) for s in students[:30]]
    )
    states = [
        "marked",
        "matched",
        "processing",
        "needs_verification",
        "recognition_failed",
        "uploaded",
    ]
    scripts = Submission.objects.bulk_create(
        [
            Submission(
                assessment_id=assessment.pk,
                enrollment_id=enrolled[i % 300].pk,
                status=states[i % 6],
                version=4,
                file="source.pdf",
                original_filename=f"script-{i}.pdf",
                recognition_method="bubble" if i % 2 else "ocr",
            )
            for i in range(600)
        ]
        + [
            Submission(
                assessment_id=old_assessment.pk,
                enrollment_id=e.pk,
                status="marked",
                file="source.pdf",
                original_filename=f"archived-{i}.pdf",
            )
            for i, e in enumerate(old_enrolled)
        ]
    )
    Submission.objects.create(
        assessment_id=assessment.pk,
        status="marked",
        file="source.pdf",
        original_filename="orphan.pdf",
    )
    Attempt.objects.bulk_create(
        [
            Attempt(
                submission_id=s.pk,
                method="ocr",
                outcome="no_match",
                processing_version="synthetic-legacy",
                region_image="crop.png",
            )
            for s in scripts
            for _ in range(2)
        ]
    )
    Job.objects.bulk_create(
        [Job(submission_id=s.pk, status="succeeded", attempts=1) for s in scripts]
    )
    Audit.objects.bulk_create(
        [
            Audit(
                submission_id=s.pk,
                actor_id=owner.pk,
                previous_status="matched",
                new_status=s.status,
                new_enrollment_id=s.enrollment_id,
                reason="Synthetic legacy audit",
            )
            for s in scripts
        ]
    )
    results = Result.objects.bulk_create(
        [
            Result(assessment_id=assessment.pk, enrollment_id=e.pk, mark=75)
            for e in enrolled
        ]
    )
    for i, state in enumerate(("sent", "queued")):
        Email.objects.create(
            result_id=results[i].pk,
            result_version=1,
            idempotency_key=f"legacy-{state}",
            subject="Historical",
            body="75 / 100",
            status=state,
        )
    return {
        "legacy_students": 300,
        "legacy_submissions": 631,
        "legacy_results": 300,
        "legacy_emails": 2,
    }


def manifest(media):
    from django.apps import apps

    labels = [
        "accounts.User",
        "courses.Course",
        "assessments.Assessment",
        "students.Student",
        "students.Enrollment",
        "submissions.Submission",
        "submissions.SubmissionAudit",
        "submissions.RecognitionAttempt",
        "submissions.RecognitionJob",
        "distribution.ScriptEmail",
    ]
    tables = {}
    for label in labels:
        rows = list(apps.get_model(label).objects.order_by("pk").values())
        tables[label] = {
            "count": len(rows),
            "sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode()
            ).hexdigest(),
        }
    files = {
        str(path.relative_to(media))
        .replace("\\", "/"): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in sorted(media.rglob("*"))
        if path.is_file()
    }
    executor = MigrationExecutor(connection)
    outstanding = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return {
        "tables": tables,
        "media": files,
        "outstanding_migrations": len(outstanding),
    }


def measure(media):
    from accounts.models import User
    from submissions.models import Submission, SubmissionAudit
    from distribution.services import schedule_script_email
    from distribution.models import ScriptEmail
    from students.models import Student
    from io import StringIO
    from django.core.management import call_command

    # Verify upgrade semantics before introducing a current snapshot delivery.
    assert (
        SubmissionAudit.objects.get(
            submission__original_filename="script-0.pdf"
        ).new_identity["student_number"]
        == "00000000"
    )
    assert (
        SubmissionAudit.objects.get(
            submission__original_filename="script-0.pdf"
        ).new_identity["origin"]
        == "migration_current_reference"
    )
    assert not Submission.objects.filter(status="marked").exists()
    assert (
        Submission.objects.get(original_filename="orphan.pdf").status
        == "needs_verification"
    )
    assert Student.objects.filter(student_number="00000000").exists()
    assert "assessments_result" not in connection.introspection.table_names()
    assert (
        ScriptEmail.objects.get(idempotency_key="legacy-queued").status == "superseded"
    )
    assert ScriptEmail.objects.get(idempotency_key="legacy-sent").body == "75 / 100"
    script = (
        Submission.objects.active()
        .filter(status="verified", enrollment__isnull=False)
        .first()
    )
    email = schedule_script_email(script)
    assert (
        email.attachment
        and email.attachment.open("rb").read() == (media / "source.pdf").read_bytes()
    )
    client = APIClient()
    client.force_authenticate(User.objects.get(email="review@example.invalid"))
    counts = {}
    for path in ("/api/submissions/", "/api/submissions/verification-queue/"):
        counts[path] = []
        for page in (1, 25, 100):
            with CaptureQueriesContext(connection) as queries:
                response = client.get(path, {"page_size": page})
            assert response.status_code == 200
            counts[path].append(
                {
                    "page_size": page,
                    "queries": len(queries),
                    "returned": len(response.data["results"]),
                }
            )
        assert [x["queries"] for x in counts[path]] == [4, 4, 4]
    from rest_framework_simplejwt.tokens import AccessToken

    jwt_client = APIClient()
    jwt_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(User.objects.get(email='review@example.invalid'))}"
    )
    jwt_counts = {}
    for path in counts:
        with CaptureQueriesContext(connection) as queries:
            response = jwt_client.get(path, {"page_size": 25})
        assert response.status_code == 200
        jwt_counts[path] = len(queries)
        assert len(queries) == 5
    assert (
        client.get(f"/api/courses/{script.assessment.course_id}/gradebook/").status_code
        == 404
    )
    output = StringIO()
    call_command("audit_database_integrity", fail_on_invalid=True, stdout=output)
    plan = (
        Submission.objects.active()
        .filter(
            assessment__course__owner_id=script.assessment.course.owner_id,
            status__in=["matched", "needs_verification"],
        )
        .order_by("created_at", "pk")[:100]
        .explain(format="json", analyze=True)
    )
    return {
        "query_counts": counts,
        "jwt_query_counts": jwt_counts,
        "integrity": json.loads(output.getvalue()),
        "queue_explain": json.loads(plan),
        "manifest": manifest(media),
    }


parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["seed-legacy", "measure", "manifest"])
parser.add_argument("--output", required=True)
args = parser.parse_args()
media = guard()
report = (
    seed_legacy(media)
    if args.phase == "seed-legacy"
    else measure(media) if args.phase == "measure" else manifest(media)
)
Path(args.output).write_text(
    json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
)
print(
    json.dumps(
        {
            "database": connection.settings_dict["NAME"],
            "phase": args.phase,
            "report": args.output,
        }
    )
)
