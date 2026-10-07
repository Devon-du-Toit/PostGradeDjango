import io
import tempfile
import zipfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from courses.models import Course
from submissions.models import Submission


class ScriptExportTests(TransactionTestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        setting = override_settings(MEDIA_ROOT=media.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.owner = User.objects.create_user(email="export@example.com")
        self.course = Course.objects.create(
            owner=self.owner, code="TEST", name="Synthetic", year=2026, semester=1
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Synthetic exam"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/assessments/{self.assessment.pk}/scripts/export/"

    def script(
        self, assessment=None, name="answers.pdf", content=b"original full script"
    ):
        return Submission.objects.create(
            assessment=assessment or self.assessment,
            original_filename=name,
            file=ContentFile(content, name="synthetic.pdf"),
        )

    def test_only_selected_assessment_original_bytes_with_unique_safe_names(self):
        first = self.script(name="../../answers.pdf", content=b"PDF all pages")
        second = self.script(name="C:\\private\\answers.pdf", content=b"image original")
        other = Assessment.objects.create(course=self.course, name="Another exam")
        self.script(other, content=b"EXCLUDED")
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("assessments.export.tempfile.TemporaryFile", return_value=handle):
            response = self.client.get(self.url)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            with zipfile.ZipFile(
                io.BytesIO(b"".join(response.streaming_content))
            ) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [f"{first.pk}_answers.pdf", f"{second.pk}_answers.pdf"],
                )
                self.assertEqual(archive.read(archive.namelist()[0]), b"PDF all pages")
                self.assertEqual(archive.read(archive.namelist()[1]), b"image original")
        finally:
            response.close()
        self.assertTrue(handle.closed)

    def test_other_owner_not_visible_even_admin(self):
        stranger = User.objects.create_user(
            email="stranger@example.com", is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_denied(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_empty_has_clear_message(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertIn("no uploaded scripts", response.data["detail"])

    def test_archived_assessment_not_visible(self):
        self.assessment.archive()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_archived_course_not_visible(self):
        self.course.archive()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_missing_original_fails_without_partial_zip(self):
        script = self.script()
        script.file.storage.delete(script.file.name)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertIn("unavailable", response.data["detail"])

    @override_settings(MAX_SCRIPT_EXPORT_FILES=1)
    def test_file_count_limit(self):
        self.script()
        self.script()
        self.assertEqual(self.client.get(self.url).status_code, 413)

    @override_settings(MAX_SCRIPT_EXPORT_BYTES=2)
    def test_actual_read_byte_limit_and_cleanup(self):
        self.script()
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("assessments.export.tempfile.TemporaryFile", return_value=handle):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 413)
            self.assertTrue(handle.closed)

    def test_disk_failure_is_clear(self):
        self.script()
        with patch(
            "assessments.export.tempfile.TemporaryFile",
            side_effect=OSError("private disk path"),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private disk path", str(response.data))
