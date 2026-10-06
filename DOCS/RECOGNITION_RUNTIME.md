# Recognition runtime

Use Python 3.12 and install requirements.txt in a new virtual environment. The OCR pins remain PaddleOCR 3.7.0, PaddleX 3.7.2, PaddlePaddle 3.3.1 and NumPy 2.3.5. PaddleOCR's wheel metadata requires `paddlex[ocr-core]>=3.7.0,<3.8.0`; PaddleX's ocr-core metadata requires `opencv-contrib-python==4.10.0.84` and its NumPy range is `>=1.24,<2.4`.

Only opencv-contrib-python 4.10.0.84 supplies cv2. The former explicit opencv-python-headless 5.0.0.93 pin has been removed: both wheels install the same namespace/files, making the imported runtime dependent on installation order. Using a contrib-headless replacement would not satisfy PaddleX's declared dependency. Docker retains libgl1, libglib2.0-0 and libgomp1 for the supported contrib/Paddle runtime.

Recreate existing environments that have multiple OpenCV distributions. Uninstalling one overlapping wheel can remove files belonging to the other. Do not copy packages from an old environment or install with --no-deps.

```sh
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -r requirements.txt
python -m pip check
python tools/check_recognition_runtime.py
python manage.py test
python -m submissions.tests.evaluate_bubbles --seed 729163 --count 64 --check
```

Tests require PostgreSQL and the configured test environment. Real OCR tests initialize the same lazy get_ocr() engine as the worker and use the committed localization JPEGs plus a generated PDF. find_student_number_text remains supported and covered. The bubble evaluation includes 64 clear synthetic samples and 32 ambiguous samples; its JSON must report 64 exact, zero false clear readings and zero unsafe ambiguous readings. Synthetic metrics do not establish accuracy on unseen physical scans.

Docker and both CI test jobs install the same requirements and reject package metadata conflicts and OpenCV ABI/smoke failures. Full CI runs all OCR, document, quality, bubble and workflow tests. A successful local Windows run does not replace the Linux integration CI or a Docker build.

## Clean-environment validation, 7 October 2026

A fresh Windows Python 3.12 environment installed all runtime pins with no pip conflicts. The single OpenCV wheel and NumPy ABI/smoke checks passed. All 408 backend tests passed, including real OCR localization, real JPEG/PDF matching, document/quality tests and bubble workflows. The existing OCR wrapper expectations remain unchanged. The held-out bubble evaluation produced 64/64 exact numbers, zero false clear readings and zero unsafe clear readings on 32 ambiguous samples; all seven supplied PDFs produced identical candidates, ambiguity and templates to the previous headless runtime.

Linux Python 3.12 wheel resolution also succeeded, and Linux CI passed its runtime consistency/smoke check. Full Linux integration CI remains the merge gate; no local Docker build was run because the daemon was unavailable. Aggregate evidence is in [recognition-runtime-2026-10-07.json](evidence/recognition-runtime-2026-10-07.json); student identities and source PDFs are excluded.
