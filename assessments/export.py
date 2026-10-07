"""Bounded, private export of the original assessment upload bytes."""

import re
import tempfile
import zipfile

from django.conf import settings
from rest_framework.exceptions import APIException


class ExportUnavailable(APIException):
    status_code = 409
    default_detail = (
        "An uploaded script is unavailable. Restore it and retry the export."
    )


class ExportTooLarge(APIException):
    status_code = 413
    default_detail = "This assessment exceeds the script export limit. Download scripts individually."


def archive_name(submission):
    # Never use storage directories, user path components, or unsafe ZIP entry names.
    basename = submission.original_filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"[^A-Za-z0-9._-]", "_", basename).strip(".")[:180]
    return f"{submission.pk}_{basename or 'script'}"


def build_script_archive(submissions):
    """Return a rewound temporary file; the FileResponse owns its final cleanup."""
    max_files = settings.MAX_SCRIPT_EXPORT_FILES
    max_bytes = settings.MAX_SCRIPT_EXPORT_BYTES
    # Snapshot metadata before opening storage, independent of response streaming.
    scripts = list(submissions.order_by("id")[: max_files + 1])
    if len(scripts) > max_files:
        raise ExportTooLarge()
    if not scripts:
        return None
    archive = tempfile.TemporaryFile(mode="w+b")
    try:
        total = 0
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            for script in scripts:
                if not script.file:
                    raise ExportUnavailable()
                try:
                    source = script.file.open("rb")
                except (OSError, ValueError) as exc:
                    raise ExportUnavailable() from exc
                with source, output.open(archive_name(script), "w") as target:
                    while chunk := source.read(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ExportTooLarge()
                        target.write(chunk)
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise
