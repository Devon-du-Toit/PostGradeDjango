# CI Pipeline

The CI pipeline is defined in .github/workflows/ci.yml. It runs on every push and PR.

## Jobs

### unit (fast, mocked)

Runs first. Mocks OCR / OpenCV / PaddleOCR.

Tests:
- submissions.tests.test_emailing
- submissions.tests.test_submissions
- submissions.tests.test_verification

### integration (slow, OCR)

Runs only after unit passes. Downloads PaddleOCR models on first run (cached after).

Runs the **entire test suite** (`python manage.py test`), including the tests that use real OCR. New test modules are picked up automatically; there is no list to keep up to date. (Until 1 October 2026 this job ran four named modules, so 22 of the 29 test modules never ran in CI.)

## Model / runtime setup

The integration job requires Python 3.12, paddleocr==3.7.0, paddlepaddle==3.3.1, opencv-contrib-python, opencv-python-headless, and PaddleOCR models (~140 MB at ~/.paddlex).

Models are cached under the key paddlex-models-v1. Bump the key if the model version changes.

PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True skips the connectivity check on every run.

## Rules

- CI must be green to merge.
- If you change a model, run python manage.py makemigrations and commit the file.
- New tests that mock OCR go in the unit job.
- New tests that use real image processing go in the integration job.
