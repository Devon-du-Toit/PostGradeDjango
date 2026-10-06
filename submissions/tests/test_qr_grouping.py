"""Synthetic pages only: no student-identifying PDFs are committed."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event
from unittest.mock import patch

import cv2
import pymupdf
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from assessments.serializers import AssessmentSerializer
from courses.models import Course
from distribution.services import schedule_script_email
from students.models import Enrollment, Student
from submissions.models import ScriptUpload, Submission
from submissions.qr import group_issues, parse_qr, review_page
from submissions.recognition.service import recognize_group
from submissions.recognition.types import RecognitionResult
from submissions.services import create_submission
from submissions.tests.helpers import TemporaryMediaMixin
from submissions.verification import verify_submission


def paper(values):
    with pymupdf.open() as document:
        for value in values:
            page = document.new_page(width=595, height=842)
            page.insert_text((50, 50), value or "No QR on this page")
            if value:
                code = cv2.QRCodeEncoder_create().encode(value)
                code = cv2.copyMakeBorder(
                    code, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255
                )
                code = cv2.resize(code, (330, 330), interpolation=cv2.INTER_NEAREST)
                success, encoded = cv2.imencode(".png", code)
                assert success
                page.insert_image(
                    pymupdf.Rect(370, 620, 540, 790), stream=encoded.tobytes()
                )
        return SimpleUploadedFile(
            "synthetic.pdf", document.tobytes(), content_type="application/pdf"
        )


def qr(label, number=1, module="CMPG211"):
    return f"{module},20230412,KT2,{label},#{number}"


class QRIntakeTests(TemporaryMediaMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass"
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="testpass"
        )
        self.course = Course.objects.create(
            owner=self.user, code="CMPG211", name="Synthetic", year=2023, semester=1
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            name="KT2",
            date=date(2023, 4, 12),
            qr_test="KT2",
            expected_qr_page_labels=["P1", "P3"],
        )
        self.enrollment = Enrollment.objects.create(
            course=self.course,
            student=Student.objects.create(
                owner=self.user,
                student_number="12345678",
                first_name="Synthetic",
                last_name="One",
                email="one@example.com",
            ),
        )
        self.second = Enrollment.objects.create(
            course=self.course,
            student=Student.objects.create(
                owner=self.user,
                student_number="87654321",
                first_name="Synthetic",
                last_name="Two",
                email="two@example.com",
            ),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, values):
        return create_submission(
            dict(
                assessment=self.assessment,
                file=paper(values),
                recognition_method="bubble",
            ),
            self.user,
        )

    def ready(self, submission):
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.NEEDS_VERIFICATION
        )
        submission.refresh_from_db()

    def test_parser_rejects_malformed_fields(self):
        for value in (
            "not QR",
            qr("P0"),
            "CMPG211,20230230,KT2,P1,#1",
            "CMPG211,20230412,KT2,P1,#0",
            qr("P1") + ",extra",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_qr(value)

    def test_real_decoder_full_pages_separate_groups_and_scrambled_order(self):
        submission = self.upload([qr("P3", 2), qr("P3"), qr("P1", 2), qr("P1")])
        self.assertEqual(len(submission.upload_group_ids), 2)
        self.assertEqual(ScriptUpload.objects.count(), 1)
        for group in Submission.objects.all():
            self.assertEqual(group_issues(group), [])
            self.assertEqual(group.pages.count(), 2)
            with (
                group.file.open("rb") as file,
                pymupdf.open(stream=file.read(), filetype="pdf") as document,
            ):
                self.assertEqual(len(document), 2)
                self.assertIn("P1", document[0].get_text())
                self.assertIn("P3", document[1].get_text())
                self.assertEqual(document[0].rect.width, 595)
                other_number = (
                    "#2" if group.qr_metadata["test_number"] == "#1" else "#1"
                )
                self.assertNotIn(other_number, document[0].get_text())

    def test_pending_page_before_identity_links_only_after_verification(self):
        group = self.upload([qr("P3")])
        self.assertIn("missing:P1", group_issues(group))
        complete = self.upload([qr("P1")])
        self.assertEqual(group.pk, complete.pk)
        self.assertFalse(complete.pages.exclude(linked_enrollment=None).exists())
        self.ready(complete)
        verify_submission(
            complete, self.enrollment, self.user, expected_version=complete.version
        )
        self.assertEqual(
            set(complete.pages.values_list("linked_enrollment_id", flat=True)),
            {self.enrollment.pk},
        )

    def test_missing_duplicate_unexpected_and_unreadable_review(self):
        group = self.upload([qr("P1"), qr("P1"), qr("P5")])
        self.assertEqual(
            set(group_issues(group)), {"duplicate:P1", "missing:P3", "unexpected:P5"}
        )
        self.ready(group)
        with self.assertRaises(ValidationError):
            verify_submission(group, self.enrollment, self.user)
        unreadable = self.upload([None])
        self.assertIn("unreadable_qr", group_issues(unreadable))

    def test_conflicting_test_review(self):
        group = self.upload([qr("P1", module="OTHER"), qr("P3", module="OTHER")])
        self.assertIn("conflicting_test", group_issues(group))

    def test_unclear_student_page_keeps_correct_group(self):
        group = self.upload([qr("P1"), qr("P3")])

        def recognition(page, *, attempt):
            first = page.file.name == group.pages.first().file.name
            attempt.outcome = "image_unusable" if first else "matched"
            attempt.quality_issues = ["Blurred"] if first else []
            attempt.save()
            return RecognitionResult(
                enrollment=None if first else self.enrollment, reason=None
            )

        with patch(
            "submissions.recognition.service.recognize_single_submission",
            side_effect=recognition,
        ):
            result = recognize_group(group)
        self.assertEqual(result.enrollment, self.enrollment)
        self.assertEqual(group.pages.first().quality_issues, ["Blurred"])
        self.assertEqual(group.pages.count(), 2)

    def test_conflicting_student_requires_audited_review(self):
        group = self.upload([qr("P1"), qr("P3")])
        pages = list(group.pages.all())
        pages[0].suggested_enrollment = self.enrollment
        pages[0].save()
        pages[1].suggested_enrollment = self.second
        pages[1].save()
        self.ready(group)
        with self.assertRaises(ValidationError):
            verify_submission(group, self.enrollment, self.user)
        group = review_page(
            group.pk,
            pages[1].pk,
            dict(
                version=group.version,
                reason="Lecturer checked original",
                reviewed_enrollment=self.enrollment.pk,
            ),
            self.user,
        )
        verify_submission(
            group, self.enrollment, self.user, expected_version=group.version
        )
        self.assertTrue(group.pages.get(pk=pages[1].pk).review_history)

    def test_late_page_invalidates_verified_delivery(self):
        group = self.upload([qr("P1"), qr("P3")])
        self.ready(group)
        verify_submission(group, self.enrollment, self.user)
        email = schedule_script_email(group)
        version = group.version
        group = self.upload([qr("P3")])
        email.refresh_from_db()
        self.assertEqual(email.status, "superseded")
        self.assertGreater(group.version, version)
        self.assertEqual(group.status, "processing")
        self.assertIsNone(group.enrollment)
        self.assertFalse(group.pages.exclude(linked_enrollment=None).exists())
        with self.assertRaises(ValidationError):
            schedule_script_email(group)

    def test_duplicate_exclusion_retains_original_page(self):
        group = self.upload([qr("P1"), qr("P3"), qr("P3")])
        page = group.pages.last()
        group = review_page(
            group.pk,
            page.pk,
            dict(version=group.version, reason="Duplicate scan", exclude=True),
            self.user,
        )
        self.assertEqual(group.pages.count(), 3)
        self.assertEqual(group_issues(group), [])
        with (
            group.file.open("rb") as file,
            pymupdf.open(stream=file.read(), filetype="pdf") as document,
        ):
            self.assertEqual(len(document), 2)

    def test_unreadable_page_can_be_repaired_and_moved(self):
        group = self.upload([qr("P1")])
        bad = self.upload([None])
        page = bad.pages.first()
        review_page(
            bad.pk,
            page.pk,
            dict(
                version=bad.version,
                destination_submission=group.pk,
                destination_version=group.version,
                qr_value=qr("P3"),
                reason="Read original printed page",
            ),
            self.user,
        )
        group.refresh_from_db()
        self.assertEqual(group_issues(group), [])
        self.assertEqual(group.pages.count(), 2)

    def test_review_requires_versions_and_reason(self):
        group = self.upload([qr("P1")])
        page = group.pages.first()
        for payload in (
            {"version": group.version},
            {"version": 99, "reason": "Review"},
        ):
            from rest_framework.exceptions import ValidationError as APIError

            with self.assertRaises(APIError):
                review_page(group.pk, page.pk, payload, self.user)

    def test_private_page_and_source_downloads(self):
        group = self.upload([qr("P1"), qr("P3")])
        page = group.pages.first()
        for url in (
            f"/api/submissions/{group.pk}/pages/{page.pk}/file/",
            f"/api/submissions/{group.pk}/uploads/{page.upload_id}/file/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response._resource_closers[0]()
            self.client.force_authenticate(self.other)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.force_authenticate(self.user)
        self.assessment.archive()
        self.assertEqual(
            self.client.get(
                f"/api/submissions/{group.pk}/pages/{page.pk}/file/"
            ).status_code,
            404,
        )

    def test_api_group_fields_and_config_validation(self):
        group = self.upload([qr("P3"), qr("P1")])
        response = self.client.get(f"/api/submissions/{group.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [page["page_label"] for page in response.data["grouped_pages"]],
            ["P1", "P3"],
        )
        self.assertEqual(response.data["qr_group_status"], "pending_identification")
        for labels in (["P1", "P1"], [{}], ["bad"], "P1"):
            serializer = AssessmentSerializer(
                data={"name": "Synthetic", "expected_qr_page_labels": labels}
            )
            self.assertFalse(serializer.is_valid())

    def test_invalid_review_types_return_400(self):
        group = self.upload([qr("P1")])
        page = group.pages.first()
        for payload in (
            {"version": group.version, "reason": "Review", "qr_value": 1},
            {"version": group.version, "reason": "Review", "qr_value": "bad"},
            {"version": group.version, "reason": "Review", "reviewed_enrollment": True},
        ):
            response = self.client.post(
                f"/api/submissions/{group.pk}/pages/{page.pk}/review/",
                payload,
                format="json",
            )
            self.assertEqual(response.status_code, 400)

    def test_failed_rebuild_rolls_back_all_rows_and_blobs(self):
        from pathlib import Path

        before = set(Path(self.media_root).rglob("*.pdf"))
        original_save = Submission.save

        def fail_canonical(instance, *args, **kwargs):
            if kwargs.get("update_fields") and "file" in kwargs["update_fields"]:
                raise RuntimeError("Synthetic DB error")
            return original_save(instance, *args, **kwargs)

        with (
            patch.object(Submission, "save", fail_canonical),
            self.assertRaises(RuntimeError),
        ):
            self.upload([qr("P1"), qr("P3")])
        self.assertEqual(Submission.objects.count(), 0)
        self.assertEqual(ScriptUpload.objects.count(), 0)
        self.assertEqual(set(Path(self.media_root).rglob("*.pdf")), before)

    def test_review_failed_second_rebuild_keeps_original_storage(self):
        group = self.upload([qr("P1")])
        bad = self.upload([None])
        page = bad.pages.first()
        from pathlib import Path

        before = set(Path(self.media_root).rglob("*.pdf"))
        original_save = Submission.save

        def fail_canonical(instance, *args, **kwargs):
            if kwargs.get("update_fields") and "file" in kwargs["update_fields"]:
                raise RuntimeError("Synthetic DB error")
            return original_save(instance, *args, **kwargs)

        with (
            patch.object(Submission, "save", fail_canonical),
            self.assertRaises(RuntimeError),
        ):
            review_page(
                bad.pk,
                page.pk,
                dict(
                    version=bad.version,
                    destination_submission=group.pk,
                    destination_version=group.version,
                    qr_value=qr("P3"),
                    reason="Read original",
                ),
                self.user,
            )
        page.refresh_from_db()
        self.assertEqual(page.submission_id, bad.pk)
        self.assertEqual(set(Path(self.media_root).rglob("*.pdf")), before)

    @override_settings(MAX_QR_GROUP_PAGES=2)
    def test_retained_page_limit_rejects_whole_late_upload_without_changes(self):
        from pathlib import Path

        from rest_framework.exceptions import ValidationError as APIError

        group = self.upload([qr("P1"), qr("P3")])
        version = group.version
        before = set(Path(self.media_root).rglob("*.pdf"))
        with self.assertRaises(APIError):
            self.upload([qr("P3")])
        group.refresh_from_db()
        self.assertEqual(group.version, version)
        self.assertEqual(group.pages.count(), 2)
        self.assertEqual(ScriptUpload.objects.count(), 1)
        self.assertEqual(set(Path(self.media_root).rglob("*.pdf")), before)


class QRConcurrencyTests(TemporaryMediaMixin, TransactionTestCase):
    ready = QRIntakeTests.ready

    def upload_fast(self, label):
        return create_submission(
            dict(
                assessment=self.assessment,
                file=SimpleUploadedFile(label + ".pdf", self.raw),
                recognition_method="bubble",
            ),
            self.user,
        )

    def setUp(self):
        QRIntakeTests.setUp(self)
        self.raw = paper([None]).read()

        def extract(uploaded):
            label = uploaded.name.split(".")[0]
            return self.raw, [(1, parse_qr(qr(label)), "readable", self.raw)]

        patcher = patch("submissions.qr.extract_pages", side_effect=extract)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parallel_intake_serializes_one_group_and_one_active_job(self):
        barrier = Barrier(2)

        def upload(label):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.upload_fast(label).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(upload, ["P1", "P3"]))
        self.assertEqual(len(set(ids)), 1)
        group = Submission.objects.get(pk=ids[0])
        self.assertEqual(group.pages.count(), 2)
        self.assertEqual(group_issues(group), [])
        self.assertEqual(
            group.recognition_jobs.filter(status__in=["queued", "running"]).count(), 1
        )

    def test_stale_recognition_cannot_rewrite_pages_after_late_intake(self):
        group = self.upload_fast("P1")
        started, release = Event(), Event()

        def recognize(page, *, attempt):
            started.set()
            release.wait(timeout=10)
            return RecognitionResult(enrollment=self.enrollment, reason=None)

        def worker():
            close_old_connections()
            try:
                return recognize_group(Submission.objects.get(pk=group.pk))
            finally:
                close_old_connections()

        with (
            patch(
                "submissions.recognition.service.recognize_single_submission",
                side_effect=recognize,
            ),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(worker)
            self.assertTrue(started.wait(timeout=10))
            self.upload_fast("P3")
            release.set()
            result = future.result(timeout=10)
        self.assertIsNone(result.enrollment)
        self.assertFalse(group.pages.exclude(suggested_enrollment=None).exists())

    def test_parallel_verify_and_late_intake_never_leaves_linked_verified_group(self):
        group = self.upload_fast("P1")
        group = self.upload_fast("P3")
        self.ready(group)
        version = group.version
        barrier = Barrier(2)

        def operation(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if action == "upload":
                    self.upload_fast("P3")
                else:
                    try:
                        verify_submission(
                            Submission.objects.get(pk=group.pk),
                            self.enrollment,
                            self.user,
                            expected_version=version,
                        )
                    except ValidationError:
                        pass
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(operation, ["upload", "verify"]))
        group.refresh_from_db()
        self.assertEqual(group.status, "processing")
        self.assertIsNone(group.enrollment_id)
        self.assertFalse(group.pages.exclude(linked_enrollment=None).exists())

    def test_expired_worker_cannot_publish_page_evidence_for_new_lease(self):
        from submissions.models import RecognitionJob

        group = self.upload_fast("P1")
        group = self.upload_fast("P3")
        job = group.recognition_jobs.filter(status="queued").get()
        job.status, job.attempts = RecognitionJob.Status.RUNNING, 2
        job.save()

        def obsolete(page, *, attempt):
            attempt.outcome = "matched"
            attempt.quality_issues = ["Obsolete evidence"]
            attempt.save()
            return RecognitionResult(enrollment=self.second, reason=None)

        with patch(
            "submissions.recognition.service.recognize_single_submission",
            side_effect=obsolete,
        ):
            result = recognize_group(group, job_id=job.pk, claimed_attempt=1)
        self.assertIsNone(result.enrollment)
        self.assertFalse(group.pages.exclude(suggested_enrollment=None).exists())
        self.assertFalse(group.pages.exclude(quality_issues=[]).exists())
