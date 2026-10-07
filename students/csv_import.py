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

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from courses.models import Course
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
BULK_BATCH_SIZE = 500


class CSVStudentSerializer(StudentSerializer):
    """Reuse field validation; owner-scoped uniqueness is checked in one lookup."""

    def validate_student_number(self, student_number):
        return student_number


class CSVFileError(Exception):
    """A problem with the file itself, not any particular row."""

    def __init__(self, detail, status_code=400, errors=None):
        self.detail = detail
        self.status_code = status_code
        self.errors = errors or []
        super().__init__(detail)


@dataclass
class RowMismatch:
    row: int
    student_number: str
    differences: dict


def _errors_to_message(field_errors):
    parts = []
    for field_name, messages in field_errors.items():
        if isinstance(messages, (list, tuple)):
            messages = " ".join(str(m) for m in messages)
        parts.append(f"{field_name}: {messages}")
    return " ".join(parts)


def _error_entry(row_number, errors, student_number=""):
    return {
        "row": row_number,
        "student_number": student_number,
        "errors": errors,
        "message": _errors_to_message(errors),
    }


@dataclass
class ImportPlan:
    owner_id: int | None = None
    expected_students: dict = field(default_factory=dict)
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
            "total": self.rows_processed,
            "failed": len(self.errors),
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
            f"File is too large. Maximum allowed size is " f"{max_mb:.1f} MB."
        )

    raw_bytes = uploaded_file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise CSVFileError("File exceeds the maximum allowed size.")

    try:
        # utf-8-sig transparently strips a BOM if present, and
        # behaves exactly like plain utf-8 when there isn't one.
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVFileError("File could not be read as UTF-8 text.")


def _build_reader(decoded_text):
    reader = csv.reader(io.StringIO(decoded_text, newline=""), strict=True)
    try:
        header = [name.strip() for name in next(reader)]
    except StopIteration:
        raise CSVFileError("The CSV file is empty.")
    except csv.Error as exc:
        raise CSVFileError(f"Invalid CSV header: {exc}") from exc
    if any(not name for name in header):
        raise CSVFileError("Header contains a blank column name.")
    if len(header) != len(set(header)):
        raise CSVFileError("Header contains duplicate column names.")
    missing = set(REQUIRED_COLUMNS) - set(header)
    if missing:
        raise CSVFileError("Missing required columns: " + ", ".join(sorted(missing)))
    return reader, header


def _extract_fields(row):
    """
    Pull the four required fields out of a DictReader row, stripped
    of whitespace. A value that was missing (short row) comes back
    from DictReader as None; that's normalized to "" here so every
    downstream check only has to deal with strings.
    """
    return {column: (row.get(column) or "").strip() for column in REQUIRED_COLUMNS}


def _is_blank_row(fields):
    return all(value == "" for value in fields.values())


def build_import_plan(
    owner,
    uploaded_file,
    update_existing=False,
    serializer_context=None,
    course=None,
):
    """
    Validate every row of the uploaded CSV and return an ImportPlan
    describing exactly what would happen. Never writes to the
    database - the caller decides whether to apply it.
    """
    decoded_text = _read_decoded_text(uploaded_file)
    reader, header = _build_reader(decoded_text)

    plan = ImportPlan(owner_id=owner.pk)
    seen_student_numbers = {}

    parsed_rows = []
    records = 0
    while True:
        # Physical starting line, including blank lines and multiline CSV records.
        row_number = reader.line_num + 1
        try:
            raw_row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            plan.errors.append(
                _error_entry(row_number, {"row": f"Malformed CSV: {exc}"})
            )
            break  # The parser cannot reliably recover after broken quoting.
        records += 1
        if records > MAX_ROWS:
            plan.errors.append(
                _error_entry(
                    row_number, {"file": f"File has more than {MAX_ROWS} data rows."}
                )
            )
            break
        if not raw_row or (len(raw_row) == 1 and not raw_row[0].strip()):
            continue
        row = dict(zip(header, raw_row))
        fields = _extract_fields(row)
        if len(raw_row) != len(header):
            plan.rows_processed += 1
            plan.errors.append(
                _error_entry(
                    row_number,
                    {"row": "Row must have the same number of fields as the header."},
                    fields["student_number"],
                )
            )
            continue
        if _is_blank_row(fields) and all(not value.strip() for value in raw_row):
            continue
        plan.rows_processed += 1

        missing_fields = [column for column in REQUIRED_COLUMNS if fields[column] == ""]

        if missing_fields:
            plan.errors.append(
                _error_entry(
                    row_number,
                    {column: "This field is required." for column in missing_fields},
                    fields["student_number"],
                )
            )
            continue

        student_number = fields["student_number"]

        first_seen_row = seen_student_numbers.get(student_number)

        if first_seen_row is not None:
            plan.errors.append(
                _error_entry(
                    row_number,
                    {
                        "student_number": (
                            f"Duplicate student_number "
                            f"'{student_number}' in file "
                            f"(first seen on row {first_seen_row})."
                        )
                    },
                    student_number,
                )
            )
            continue

        seen_student_numbers[student_number] = row_number

        parsed_rows.append((row_number, fields))

    existing_students = {
        student.student_number: student
        for student in Student.objects.filter(
            owner=owner, student_number__in=seen_student_numbers
        )
    }
    withdrawn_ids = (
        set(
            Enrollment.objects.filter(
                course=course, withdrawn_at__isnull=False
            ).values_list("student_id", flat=True)
        )
        if course is not None
        else set()
    )
    for row_number, fields in parsed_rows:
        student_number = fields["student_number"]
        existing_student = existing_students.get(student_number)

        if existing_student is not None and (
            existing_student.archived_at is not None
            or existing_student.pk in withdrawn_ids
        ):
            plan.errors.append(
                _error_entry(
                    row_number,
                    {
                        "student_number": "Restore the archived contact or withdrawn membership explicitly before importing."
                    },
                    student_number,
                )
            )
            continue
        plan.expected_students[student_number] = {
            "row": row_number,
            "pk": existing_student.pk if existing_student else None,
            "fields": (
                {key: getattr(existing_student, key) for key in REQUIRED_COLUMNS}
                if existing_student
                else None
            ),
        }

        if existing_student is None:
            serializer = CSVStudentSerializer(data=fields, context=serializer_context)

            if not serializer.is_valid():
                plan.errors.append(
                    _error_entry(
                        row_number,
                        serializer.errors,
                        student_number,
                    )
                )
                continue

            plan.to_create.append(serializer.validated_data)
            continue

        serializer = CSVStudentSerializer(
            existing_student, data=fields, context=serializer_context
        )
        if not serializer.is_valid():
            plan.errors.append(
                _error_entry(row_number, serializer.errors, student_number)
            )
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
            plan.to_update.append((existing_student, serializer.validated_data))
        else:
            plan.to_enroll_unchanged.append(existing_student)

    plan.errors.sort(key=lambda error: error["row"])
    return plan


def apply_import_plan(owner, course, plan):
    if not plan.is_valid or plan.owner_id != owner.pk:
        raise CSVFileError("Only a valid plan for this owner can be applied.")
    try:
        with transaction.atomic():
            try:
                course = (
                    Course.objects.active()
                    .select_for_update()
                    .get(pk=course.pk, owner=owner)
                )
            except Course.DoesNotExist as exc:
                raise CSVFileError(
                    "The course is archived or no longer available.", status_code=404
                ) from exc
            expected_ids = [
                item["pk"]
                for item in plan.expected_students.values()
                if item["pk"] is not None
            ]
            locked = list(
                Student.objects.select_for_update()
                .filter(owner=owner)
                .filter(
                    Q(student_number__in=list(plan.expected_students))
                    | Q(pk__in=expected_ids)
                )
                .order_by("pk")
            )
            by_number = {student.student_number: student for student in locked}
            conflicts = []
            for number, expected in plan.expected_students.items():
                current = by_number.get(number)
                if getattr(current, "pk", None) != expected["pk"] or (
                    current is not None
                    and {key: getattr(current, key) for key in REQUIRED_COLUMNS}
                    != expected["fields"]
                ):
                    conflicts.append(
                        _error_entry(
                            expected["row"],
                            {
                                "student_number": "Student details changed during import. Preview again."
                            },
                            number,
                        )
                    )
            if (
                any(student.archived_at is not None for student in locked)
                or Enrollment.objects.filter(
                    course=course,
                    student_id__in=[student.pk for student in locked],
                    withdrawn_at__isnull=False,
                ).exists()
            ):
                raise CSVFileError(
                    "Archived contacts and withdrawn memberships require explicit restore. Nothing was saved.",
                    status_code=409,
                )
            if conflicts:
                raise CSVFileError(
                    "Class list changed. Nothing was saved. Preview again.",
                    status_code=409,
                    errors=conflicts,
                )
            students = Student.objects.bulk_create(
                [
                    Student(**{**validated, "owner": owner})
                    for validated in plan.to_create
                ],
                batch_size=BULK_BATCH_SIZE,
            )
            updates = []
            updated_at = timezone.now()
            for student, validated in plan.to_update:
                current = by_number[student.student_number]
                for attr in TRACKED_FIELDS:
                    setattr(current, attr, validated[attr])
                current.updated_at = updated_at
                current.version += 1
                updates.append(current)
            if updates:
                Student.objects.bulk_update(
                    updates,
                    [*TRACKED_FIELDS, "updated_at", "version"],
                    batch_size=BULK_BATCH_SIZE,
                )
            students.extend(updates)
            students.extend(
                by_number[student.student_number]
                for student in plan.to_enroll_unchanged
            )
            student_ids = sorted(student.pk for student in students)
            enrolled_ids = set(
                Enrollment.objects.filter(
                    course=course, student_id__in=student_ids
                ).values_list("student_id", flat=True)
            )
            Enrollment.objects.bulk_create(
                [
                    Enrollment(course=course, student_id=student_id)
                    for student_id in student_ids
                    if student_id not in enrolled_ids
                ],
                batch_size=BULK_BATCH_SIZE,
            )
    except IntegrityError as exc:
        # A concurrent create/delete may commit after preflight. The atomic block
        # has rolled back before this public, non-database error is returned.
        raise CSVFileError(
            "Class list changed during import. Nothing was saved. Preview again.",
            status_code=409,
        ) from exc
