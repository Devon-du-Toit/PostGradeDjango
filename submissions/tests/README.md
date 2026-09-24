 # Recognition Test Guide

The recognition test suite separates deterministic mocked tests from slower OCR/OpenCV integration tests.

## Deterministic Regression Tests

Run:

```bash
python manage.py test submissions.tests.test_recognition_regression
```

These tests use synthetic student numbers to verify:

- exact student-number matching;
- false-match prevention; and
- recognition regression metrics.

Current deterministic regression expectations:

- Exact-number matches: 4/4
- False matches: 0/3

These values apply to the synthetic regression cases and do not represent overall OCR accuracy.

## Mocked Recognition Service Tests

Run:

```bash
python manage.py test submissions.tests.test_recognition_service
```

These tests mock the OCR-related functions so that recognition service behaviour can be tested deterministically without running the OCR model.

## Slower OCR/OpenCV Integration Tests

Run:

```bash
python manage.py test submissions.tests.test_recognition_integration
```

These tests exercise the real recognition path using image and PDF fixtures.

The integration tests require the project's recognition dependencies, including:

- PaddleOCR
- OpenCV
- PyMuPDF

PaddleOCR may download the required model files on the first run. Once downloaded, the locally cached models can be reused on later runs.

## CI Integration

The deterministic mocked tests and slower OCR/OpenCV integration tests can be executed separately in CI.

The CI workflow and PostgreSQL configuration are handled separately from the recognition regression test cases.