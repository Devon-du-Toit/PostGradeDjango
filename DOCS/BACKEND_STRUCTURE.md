# Backend structure and cleanup (#12)

This release changes structure/tooling only. Request payloads, status/error messages, ownership checks, locks, audit/version behavior, recognition thresholds, file limits and delivery policy remain unchanged. Marking is already retired and is not recreated.

## Boundaries

| Module | Responsibility |
| --- | --- |
| submissions.serializers | Request/field/content validation and API representation. Creation/replacement delegate after validation. |
| submissions.services | Validated upload persistence and versioned file replacement: parent/job/submission locks, audit creation/transitions, job cancellation/enqueue, unsent-mail supersession and after-commit old-file cleanup. |
| submissions.verification | Existing verification/correction transaction and explicit reason/version rules. |
| submissions.jobs | Recognition queue, lease/attempt fencing, retries and worker completion. |
| submissions.recognition.service | Existing OCR/bubble routing and recognition evidence. |
| courses.lifecycle | Shared active-course lock and existing archive work cancellation. |
| submissions.lifecycle | Course-before-assessment locking for submission operations. |
| students.csv_import | Existing parse/preview/import plan and atomic application. HTTP views retain response orchestration. |
| distribution.services / dispatch | Existing delivery request/approval/idempotency and mail-worker dispatch. |

The mixed upload/replacement responsibilities previously occupied over 100 lines in the serializer. They now have explicit service entry points with actor parameters. Services expect validated data; serializers still validate uploaded bytes, ownership and field shapes. Submission has no many-to-many fields, so its existing ModelSerializer persistence maps to queryset create and attribute assignment/save without changing persistence order. The shared course lock replaces repeated active/owner-scoped lock queries in course, assessment, enrollment and submission writes. It preserves the existing optional owner scope for internal workflow calls.

The formatting/import cleanup is a separate commit from service extraction and CI/documentation, allowing review without mixing mechanical changes with workflow movement. A duplicated StudentEmailTests class shadowed two earlier email tests; its distinct name restores discovery of both existing tests. No assertions were removed.

## Tooling

requirements-dev.txt pins Ruff 0.16.10 and Black 26.10.0 for Python 3.12. Black is the sole formatter (88 columns); Ruff checks import ordering, unused/repeated names and basic syntax/errors. Migrations, tests and review tools share the same style. The sole E402 exception covers the standalone database-review tool whose Django setup must precede ORM imports; signal-registration imports keep explicit F401 annotations.

```text
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m black --workers 1 --check .
```

Developer fixes are explicit: `python -m ruff check . --fix` and `python -m black --workers 1 .`. CI uses check-only commands without --fix, installs only development tools in its lint job, and gates the PostgreSQL unit/integration pipeline on that job. Single-worker formatting also avoids unnecessary subprocess fan-out in local Windows environments. .ruff_cache is ignored.

## Recognition review

All production OCR/bubble/document/quality/matching entry points remain. find_student_number_text has no current production caller but is directly exercised by the OCR localization tests and remains a supported compatibility wrapper. get_ocr stays lazy; the existing fresh-interpreter startup regression verifies that importing the API does not load PaddleOCR. PDF/JPEG/PNG support and empty/corrupt PDF errors are retained; obsolete editing comments were removed.

Source use confirms cv2 for bubble geometry/quality, NumPy for bubble scoring, PyMuPDF for PDF rasterization and Pillow for image handling. PaddleOCR/Paddle/PaddleX remain the OCR engine/runtime. The recognition runtime uses only opencv-contrib-python 4.10.0.84, as required by PaddleX. Docker/CI check installed distributions and the NumPy/OpenCV ABI before recognition. See [RECOGNITION_RUNTIME.md](RECOGNITION_RUNTIME.md) for the clean-environment review from #54. Packages loaded indirectly through OCR/settings are not removed merely because a direct import search misses them.

## Verification

Existing backend tests cover upload/replacement, stale requests, owner/archive scopes, transaction rollback, jobs, protected files, recognition matching/evidence, bubble fixtures, email delivery and database integrity. The local regression run passes 402 tests, including the two previously hidden email tests; the six tests in the two real-PaddleOCR modules remain in full CI and are unavailable in the light local environment. Ruff, Black, Django checks and migration-drift checks pass. No schema migration or Vue update is required.
