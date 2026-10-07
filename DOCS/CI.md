# CI Pipeline

The CI pipeline is defined in .github/workflows/ci.yml. It runs on pushes/PRs targeting main or master; a PR targeting a stacked feature branch may have no CI run.

## Jobs

### unit (fast, mocked)

Runs first. Mocks OCR / OpenCV / PaddleOCR.

Tests:
- submissions.tests.test_bubble_recognition
- submissions.tests.test_bubble_workflow
- submissions.tests.test_audit
- submissions.tests.test_integrity_review
- submissions.tests.test_emailing
- submissions.tests.test_submissions
- submissions.tests.test_verification
- accounts, students, courses, distribution and assessments.tests

### integration (slow, OCR)

Runs only after unit passes. Downloads PaddleOCR models on first run (cached after).

Runs the **entire test suite** (`python manage.py test`), including the tests that use real OCR. New test modules are picked up automatically; there is no list to keep up to date. (Until 1 October 2026 this job ran four named modules, so 22 of the 29 test modules never ran in CI.)

## Model / runtime setup

The integration job requires Python 3.12, paddleocr==3.7.0, paddlepaddle==3.3.1, paddlex==3.7.2, numpy==2.3.5, the single opencv-contrib-python==4.10.0.84 distribution, and PaddleOCR models (~140 MB at ~/.paddlex). PaddleX's ocr-core extra requires this exact OpenCV wheel. Do not install another cv2 distribution alongside it.

Both test jobs run `python -m pip check` and `python tools/check_recognition_runtime.py` after installation. Docker runs the same checks before initializing its OCR models. The runtime check rejects missing, conflicting or unexpected OpenCV wheels and exercises NumPy/OpenCV PNG and contour operations to detect ABI/import failures. See [RECOGNITION_RUNTIME.md](RECOGNITION_RUNTIME.md) for clean installation and validation.

Models are cached under the key paddlex-models-v1. Bump the key if the model version changes.

PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True skips the connectivity check on every run.

## Rules

- CI must be green to merge.
- If you change a model, run python manage.py makemigrations and commit the file.
- New tests that mock OCR go in the unit job.
- New tests that use real image processing go in the integration job.

## Lint and formatting

The check-only lint job installs requirements-dev.txt, runs `python -m ruff check .` and `python -m black --workers 1 --check .`. Both are enforced and neither rewrites CI files. The unit job requires lint; full integration requires unit. Ruff checks unused/repeated imports, import ordering and syntax; Black is the consistent formatter for source, tests, migrations and review tools. See [BACKEND_STRUCTURE.md](BACKEND_STRUCTURE.md) for service boundaries and recognition dependency review.

Auth lifecycle and endpoint matrix regressions live in `accounts.test_lifecycle` and `accounts.test_permissions`. They use the migrated database throttle cache and token blacklist; run `python manage.py test accounts` against PostgreSQL to include concurrent refresh fencing. Migration creates the cache table; no separate createcachetable command is needed.


Database review regressions: submissions.tests.test_integrity_review runs in the fast unit job and covers membership validation, deletion fencing, immutable audit identity and constant list query counts. Full integration includes migration coverage. tools/database_review.py is a separate guarded PostgreSQL/media drill, not a production seed or CI mail sender.

Pull requests targeting any branch run CI, including stacked feature PRs. Push-triggered CI remains limited to main/master. Test settings and fixture data are synthetic; this does not expose production credentials.
