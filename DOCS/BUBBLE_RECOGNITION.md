# Filled-bubble student number recognition

Choose `ocr` for handwritten digits, or `bubble` for filled bubbles when uploading a submission. Existing submissions and uploads that omit the method retain `ocr`. Bubble recognition never calls OCR, reads the writing boxes, extracts PDF text, or uses the QR code as an identity. The selected method persists across recognition retries. Replace a file using its current submission version to change its method.

## Algorithm and templates

The worker renders page zero of PDFs using the existing bounded upload pipeline, or reads a validated PNG/JPEG. Image geometry uses the already-installed OpenCV dependency; identity comes only from mark density.

1. Find small solid or nested square registration markers with local adaptive thresholding. Bound marker candidates and resize the geometry search to at most 1800 pixels on its longest edge.
2. Consider geometrically plausible four-marker frames. Rectify rotation, scale and perspective into a 320 × 520 image. Require the expected eight-column, ten-row printed bubble lattice; reject competing plausible grids. A separate QR finder pattern cannot satisfy that lattice.
3. Choose a versioned layout: `nwu-eight-standard-1` (markers above the heading), or `nwu-eight-compact-1` (nested markers beside the writing row). Both were found in the supplied Bubble Tests examples. Eight digits belong to these templates, not to the global Student model.
4. Measure local darkness inside each of the 80 circles, excluding the printed ring. Subtract the median unfilled-cell ink baseline. This still handles eight identical digits. Local white normalization tolerates gradual shadows.
5. Decode left to right as a string. Keep leading zeros. A clear column needs density ≥ 0.23, best-to-second separation ≥ 0.12, and no competing cell with density ≥ 0.10. Blank, multiple-filled and uncertain/erased columns have `digit: null`, a reason, and `X` in the candidate. Scores are mark-density measures, not calibrated probabilities.
6. Suggest an enrollment only for eight clear columns and an exact student-number match within the submission assessment's course. No nearest-number or fuzzy matching is used. All suggestions still require the existing lecturer verification before marking. No match, ambiguity or missing markers enters `needs_verification`.

The project owner agreed on 2026-10-06 to suggest a student only for eight clear bubbles with an exact class enrollment match. `BUBBLE_AUTO_MATCH_ENABLED=False` can disable enrollment suggestions for a deployment while retaining decoding and manual review. Default: `True`.

## API

Authenticated `GET /api/submissions/recognition-methods/` advertises `ocr` and `bubble` and the supported template versions. The Vue selector offers bubbles only after that capability is advertised, preventing an older backend from silently applying OCR to a bubble upload.

`POST /api/submissions/` uses multipart fields `assessment`, `file`, and optional `recognition_method` (`ocr` or `bubble`). Invalid methods return 400. Responses include `recognition_method`. An unrelated PATCH cannot silently change the method of a processed submission.

The existing `recognition` evidence object has additive fields:

- `method: "bubble"`, `processing_version: "bubble-1"`, and `template_version` identify the algorithm/layout.
- `raw_candidate` preserves zeros and uses `X` for undecided columns; `raw_text` remains empty.
- `column_scores` contains `{column, scores, digit, margin, reason}`. Columns are one-based; each `scores` list indexes digits 0–9.
- `column_ambiguity` keeps the existing `{column, reason}` contract with `empty`, `multiple`, or `unreadable`.
- `confidence_type: "bubble_margin"` and `confidence` contain the weakest column separation, not an OCR confidence/probability.
- `region` contains the source bounding rectangle, source image size, registration corners, page zero, and rectified size. `region_image_url` serves the rectified grid through the existing owner-checked protected image endpoint.

## Validation and limits

All seven supplied `FILLED_*.pdf` examples decoded to the visually checked bubble values, including the leading-zero example. These examples were used for layout calibration and are **not** an independent held-out accuracy set. Neither the PDFs nor their identity-bearing crops are committed.

The held-out procedural test set (seed 729163, generated after thresholds/layouts were fixed) contains 64 clear synthetic numbers across both templates, rotations, scale, perspective and gradual shadows, plus 32 ambiguous negative cases. Reproduce with:

```sh
python -m submissions.tests.evaluate_bubbles --seed 729163 --count 64
```

Measured: 64/64 clear numbers decoded exactly (100%), 0/64 incorrect clear readings (0%), and 0/32 ambiguous cases incorrectly treated as clear. The synthetic results do not establish accuracy on unseen physical scans. A larger independent anonymized scan set is still needed for deployment acceptance. Severe blur, tiny grids, missing/damaged markers, mirrored layouts, unknown templates and competing grids should be reviewed manually; the system does not fall back to OCR for bubble submissions. Only the first PDF page supplies the student-number grid, consistent with the existing recognition pipeline.

Unit tests cover blanks, multiple fills, faint marks, erasure, missing markers, QR decoys, leading zeros, repeated digits, both layouts and geometric/lighting distortions. PostgreSQL/API tests cover method persistence, exact class matching, wrong-course/near-number rejection, protected evidence, invalid selection and proof that bubble workers do not invoke OCR.
