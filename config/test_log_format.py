import json
import logging

from django.test import SimpleTestCase

from config.log_format import JsonFormatter


class JsonFormatterTests(SimpleTestCase):
    def format(self, record):
        return json.loads(JsonFormatter().format(record))

    def make_record(self, message, *args, exc_info=None):
        return logging.LogRecord(
            name="submissions.jobs",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=args,
            exc_info=exc_info,
        )

    def test_writes_one_json_object_with_the_core_fields(self):
        entry = self.format(self.make_record("Recognition job %s failed", 7))

        self.assertEqual(set(entry), {"time", "level", "logger", "message"})
        self.assertEqual(entry["level"], "WARNING")
        self.assertEqual(entry["logger"], "submissions.jobs")
        self.assertEqual(entry["message"], "Recognition job 7 failed")
        self.assertTrue(entry["time"].endswith("+00:00"))

    def test_includes_the_exception_traceback(self):
        try:
            raise RuntimeError("OCR failed")
        except RuntimeError:
            import sys

            record = self.make_record("Job failed", exc_info=sys.exc_info())

        entry = self.format(record)

        self.assertIn("RuntimeError: OCR failed", entry["exception"])

    def test_does_not_serialise_request_data_attached_to_the_record(self):
        record = self.make_record("Bad Request: %s", "/api/submissions/")
        record.request = object()  # Django attaches the request here

        entry = self.format(record)

        self.assertNotIn("request", entry)
