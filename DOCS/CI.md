# CI Pipeline

The CI pipeline is defined in .github/workflows/ci.yml. It runs on every push and PR.

## Jobs

### lint (ruff)

Runs in parallel with the tests and takes seconds (installs only ruff, from `requirements-dev.txt`). Settings are in `pyproject.toml`.

- `ruff check .` — **enforced.** Unused or duplicate imports, undefined names, syntax errors (Pyflakes rules `F`, `E9`).
- `ruff format --check .` — **not enforced yet.** About 100 files are not yet in the formatter's style; reformatting them now would conflict with every open PR. After those merge, run `ruff format .` once in its own PR, then remove `continue-on-error` from the step.

Run locally before pushing:

```bash
pip install -r requirements-dev.txt
ruff check .          # add --fix to remove unused imports automatically
ruff format --check .
```

### unit (fast, mocked)

Runs first. Mocks OCR / OpenCV / PaddleOCR.

Tests:
- submissions.tests.test_emailing
- submissions.tests.test_submissions
- submissions.tests.test_verification

### integration (slow, OCR)

Runs only after unit passes. Downloads PaddleOCR models on first run (cached after).

Tests:
- submissions.tests.test_recognition_document
- submissions.tests.test_recognition_matching
- submissions.tests.test_recognition_service
- submissions.tests.test_student_number_localization

## Model / runtime setup

The integration job requires Python 3.12, paddleocr==3.7.0, paddlepaddle==3.3.1, opencv-contrib-python, opencv-python-headless, and PaddleOCR models (~140 MB at ~/.paddlex).

Models are cached under the key paddlex-models-v1. Bump the key if the model version changes.

PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True skips the connectivity check on every run.

## Rules

- CI must be green to merge, including `ruff check`.
- If you change a model, run python manage.py makemigrations and commit the file.
- New tests that mock OCR go in the unit job.
- New tests that use real image processing go in the integration job.
