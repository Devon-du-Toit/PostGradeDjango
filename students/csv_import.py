"""
CSV import for a course's class list.

The whole file is validated up front, row by row, before anything
is written: either every row is clean and the whole import commits,
or nothing does (see decision 1 on issue #9). A matched existing
student is never silently overwritten (decision 2): by default the
row is left untouched and any difference between the file and what
is stored is reported back as a "mismatch" rather than applied, and
only an explicit update_existing=true applies the file's values.
"""

import csv
import io
from dataclasses import dataclass, field

# pyright: reportMissingModuleSource=false
from django.conf import settings
from django.db import transaction

from students.models import Enrollment, Student
from students.serializers import StudentSerializer

MAX_FILE_SIZE_BYTES = getattr(
    settings,
    "MAX_CSV_IMPORT_FILE_SIZE_BYTES",
    2 * 1024 * 1024,
)
MAX_ROWS = getattr(settings, "MAX_CSV_IMPORT_ROWS", 5000)

REQUIRED_COLUMNS = (
    "student_number",
    "first_name",
    "last_name",
    "email",
)

# Columns compared against a matched existing student to detect a
# mismatch. student_number is deliberately excluded: it's the key
# used to find the match in the first place, so it can't differ.
TRACKED_FIELDS = ("first_name", "last_name", "email")


class CSVFileError(Exception):
    """A problem with the file itself, not any particular row."""

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


@dataclass
class RowMismatch:
    row: int
    student_number: str
    differences: dict


@dataclass
class ImportPlan:
    rows_processed: int = 0
    to_create: list = field(default_factory=list)
    to_update: list = field(default_factory=list)
    to_enroll_unchanged: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def is_valid(self):
        return not self.errors

    def summary(self):
        return {
            "rows_processed": self.rows_processed,
            "created": len(self.to_create),
            "updated": len(self.to_update),
            "matched_unchanged": len(self.to_enroll_unchanged),
            "enrolled": (
                len(self.to_create)
                + len(self.to_update)
                + len(self.to_enroll_unchanged)
            ),
        }

    def mismatches_payload(self):
        return [
            {
                "row": mismatch.row,
                "student_number": mismatch.student_number,
                "differences": mismatch.differences,
            }
            for mismatch in self.mismatches
        ]


def _read_decoded_text(uploaded_file):
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        raise CSVFileError(
            f"File is too large. Maximum allowed size is "
            f"{max_mb:.1f} MB."
        )

    raw_bytes = uploaded_file.read()

    try:
        # utf-8-sig transparently strips a BOM if present, and
        # behaves exactly like plain utf-8 when there isn't one.
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVFileError(
            "File could not be read as UTF-8 text."
        )


def _build_reader(decoded_text):
    reader = csv.DictReader(io.StringIO(decoded_text))

    missing_columns = set(REQUIRED_COLUMNS) - set(
        reader.fieldnames or []
    )

    if missing_columns:
        raise CSVFileError(
            "Missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    return reader


def _extract_fields(row):
    """
    Pull the four required fields out of a DictReader row, stripped
    of whitespace. A value that was missing (short row) comes back
    from DictReader as None; that's normalized to "" here so every
    downstream check only has to deal with strings.
    """
    return {
        column: (row.get(column) or "").strip()
        for column in REQUIRED_COLUMNS
    }


def _is_blank_row(fields):
    return all(value == "" for value in fields.values())


def build_import_plan(
    owner,
    uploaded_file,
    update_existing=False,
):
    """
    Validate every row of the uploaded CSV and return an ImportPlan
    describing exactly what would happen. Never touches the
    database - the caller decides whether to apply it.
    """
    decoded_text = _read_decoded_text(uploaded_file)
    reader = _build_reader(decoded_text)

    plan = ImportPlan()
    seen_student_numbers = {}

    for row_number, row in enumerate(reader, start=2):
        if row_number - 1 > MAX_ROWS:
            plan.errors.append(
                {
                    "row": row_number,
                    "errors": {
                        "file": (
                            f"File has more than {MAX_ROWS} data "
                            "rows."
                        )
                    },
                }
            )
            break

        fields = _extract_fields(row)

        if _is_blank_row(fields):
            continue

        plan.rows_processed += 1

        if None in row:
            plan.errors.append(
                {
                    "row": row_number,
                    "errors": {
                        "row": (
                            "Row has more fields than the header."
                        )
                    },
                }
            )
            continue

        missing_fields = [
            column
            for column in REQUIRED_COLUMNS
            if fields[column] == ""
        ]

        if missing_fields:
            plan.errors.append(
                {
                    "row": row_number,
                    "errors": {
                        column: "This field is required."
                        for column in missing_fields
                    },
                }
            )
            continue

        student_number = fields["student_number"]

        first_seen_row = seen_student_numbers.get(student_number)

        if first_seen_row is not None:
            plan.errors.append(
                {
                    "row": row_number,
                    "errors": {
                        "student_number": (
                            f"Duplicate student_number "
                            f"'{student_number}' in file "
                            f"(first seen on row {first_seen_row})."
                        )
                    },
                }
            )
            continue

        seen_student_numbers[student_number] = row_number

        existing_student = Student.objects.filter(
            owner=owner,
            student_number=student_number,
        ).first()

        if existing_student is None:
            serializer = StudentSerializer(data=fields)

            if not serializer.is_valid():
                plan.errors.append(
                    {
                        "row": row_number,
                        "errors": serializer.errors,
                    }
                )
                continue

            plan.to_create.append(serializer.validated_data)
            continue

        differences = {
            column: {
                "existing": getattr(existing_student, column),
                "incoming": fields[column],
            }
            for column in TRACKED_FIELDS
            if getattr(existing_student, column) != fields[column]
        }

        if differences:
            plan.mismatches.append(
                RowMismatch(
                    row=row_number,
                    student_number=student_number,
                    differences=differences,
                )
            )

        if update_existing and differences:
            serializer = StudentSerializer(
                existing_student,
                data=fields,
            )

            if not serializer.is_valid():
                plan.errors.append(
                    {
                        "row": row_number,
                        "errors": serializer.errors,
                    }
                )
                continue

            plan.to_update.append(
                (existing_student, serializer.validated_data)
            )
        else:
            plan.to_enroll_unchanged.append(existing_student)

    return plan


def apply_import_plan(owner, course, plan):
    with transaction.atomic():
        students = []

        for validated in plan.to_create:
            students.append(
                Student.objects.create(**{**validated, "owner": owner})
            )

        for student, validated in plan.to_update:
            for attr, value in validated.items():
                setattr(student, attr, value)
            student.save()
            students.append(student)

        students.extend(plan.to_enroll_unchanged)

        for student in students:
            Enrollment.objects.get_or_create(course=course, student=student)