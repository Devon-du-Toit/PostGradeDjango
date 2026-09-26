"""
Validation for uploaded submission files.

This module checks more than the filename extension: it opens the
file's actual bytes to confirm they really are the claimed type,
and enforces size / page-count / decoded-dimension limits *before*
the (expensive) OCR recognition pipeline ever touches the file.
"""

import io
import os

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

import pymupdf
from PIL import Image


ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
}

PIL_FORMAT_BY_EXTENSION = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
}

MAX_FILE_SIZE_BYTES = getattr(
    settings, "MAX_SUBMISSION_FILE_SIZE_BYTES", 15 * 1024 * 1024
)
MAX_PDF_PAGES = getattr(settings, "MAX_SUBMISSION_PDF_PAGES", 1)
MAX_IMAGE_DIMENSION_PX = getattr(
    settings, "MAX_SUBMISSION_IMAGE_DIMENSION_PX", 6000
)


class SubmissionFileValidationError(DjangoValidationError):
    """Raised when an uploaded submission file fails validation."""


def validate_submission_file(uploaded_file):
    """
    Validate an uploaded submission file's size, extension, and
    actual decoded content.

    Raises SubmissionFileValidationError with a human-readable
    message on the first check that fails. Always leaves the
    file's stream position at 0 when it returns, so the caller
    can still save it normally afterwards.
    """
    _validate_size(uploaded_file)
    extension, kind = _validate_extension(uploaded_file.name)

    try:
        if kind == "image":
            _validate_image_content(uploaded_file, extension)
        else:
            _validate_pdf_content(uploaded_file)
    finally:
        uploaded_file.seek(0)


def _validate_size(uploaded_file):
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        raise SubmissionFileValidationError(
            f"File is too large. Maximum allowed size is "
            f"{max_mb:.0f} MB."
        )


def _validate_extension(filename):
    _, extension = os.path.splitext(filename or "")
    extension = extension.lower()

    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise SubmissionFileValidationError(
            f"Unsupported file type '{extension or 'unknown'}'. "
            f"Allowed types: {allowed}."
        )

    return extension, ALLOWED_EXTENSIONS[extension]


def _validate_image_content(uploaded_file, extension):
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()

    expected_format = PIL_FORMAT_BY_EXTENSION[extension]

    try:
        with Image.open(io.BytesIO(raw_bytes)) as probe:
            probe.verify()
    except Exception as exc:
        raise SubmissionFileValidationError(
            "File content is not a valid image."
        ) from exc

    # verify() closes/invalidates the handle it checked, so the
    # image has to be reopened to inspect format and dimensions.
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            if image.format != expected_format:
                raise SubmissionFileValidationError(
                    "File extension does not match its actual "
                    f"content (expected {expected_format}, got "
                    f"{image.format})."
                )

            width, height = image.size

    except SubmissionFileValidationError:
        raise
    except Exception as exc:
        raise SubmissionFileValidationError(
            "File content is not a valid image."
        ) from exc

    if width > MAX_IMAGE_DIMENSION_PX or height > MAX_IMAGE_DIMENSION_PX:
        raise SubmissionFileValidationError(
            "Image dimensions exceed the allowed maximum of "
            f"{MAX_IMAGE_DIMENSION_PX}px."
        )


def _validate_pdf_content(uploaded_file):
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()

    try:
        document = pymupdf.open(stream=raw_bytes, filetype="pdf")
    except Exception as exc:
        raise SubmissionFileValidationError(
            "File content is not a valid PDF."
        ) from exc

    try:
        if document.page_count < 1:
            raise SubmissionFileValidationError(
                "PDF has no pages."
            )

        if document.page_count > MAX_PDF_PAGES:
            raise SubmissionFileValidationError(
                "PDF has too many pages. Maximum allowed is "
                f"{MAX_PDF_PAGES}."
            )

        page = document[0]
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False,
        )

        if (
            pixmap.width > MAX_IMAGE_DIMENSION_PX
            or pixmap.height > MAX_IMAGE_DIMENSION_PX
        ):
            raise SubmissionFileValidationError(
                "Decoded PDF page exceeds the allowed maximum "
                f"dimension of {MAX_IMAGE_DIMENSION_PX}px."
            )
    finally:
        document.close()