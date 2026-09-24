# Recognition Evidence API

PostGrade — Group 13

Version 0.1.0

## Revision History

| Date | Version | Description | Author |
|---|---|---|---|
| 24/09/2026 | 0.1.0 | Initial recognition evidence and review API documentation (Issue #2). | Graham Robert |

## Table of Contents

1. [Introduction](#1-introduction)
2. [Conventions](#2-conventions)
3. [Authentication](#3-authentication)
4. [Submission States](#4-submission-states)
5. [Recognition Evidence](#5-recognition-evidence)
6. [Endpoints](#6-endpoints)
7. [Error Responses](#7-error-responses)
8. [Recognition Examples](#8-recognition-examples)
9. [Compatibility and Rollout](#9-compatibility-and-rollout)
10. [Issues List](#10-issues-list)

---

## 1. Introduction

### 1.1 Purpose

This document defines the REST API through which PostGrade exposes student-number recognition evidence for lecturer review. It describes the submission states, the stored recognition evidence, the endpoints that return it, and the error responses a client must handle.

Recognition evidence is stored separately from the verified identity of a script. The evidence records what the recognition process observed and suggested; the verified identity records the lecturer's decision. A lecturer correction changes the verified identity only, and the original evidence remains available.

### 1.2 Scope

In scope:

- Submission states and how recognition outcomes map to them.
- The `recognition` object returned on submission responses.
- The protected region-image endpoint.
- Error responses for these endpoints.
- Examples for OCR recognition (implemented) and bubble recognition (planned format).

Out of scope:

- Implementation of bubble recognition (Technical Specification, System Feature 6).
- Image-quality checking (Technical Specification, System Feature 5). The `quality_issues` field is defined but not yet populated.
- Email distribution endpoints.

### 1.3 Requirement Traceability

| Requirement | Source | Addressed by |
|---|---|---|
| SF5-FR6 Record the outcome of image-quality analysis | Technical Specification | `quality_issues` (Section 5.2) |
| SF6-FR7 / SF6-FR8 Flag multi-mark and empty columns | Technical Specification | `column_ambiguity` (Section 5.4) |
| SF6-FR9 Generate a confidence score | Technical Specification | `confidence`, `confidence_type` (Section 5.3) |
| SF7-FR4 Render a cropped image of the recognition region | Technical Specification | `region`, `region_image_url`, Section 6.3 |
| SF7-FR6 Log manual override metadata | Technical Specification | Evidence retained after verification (Section 6.4) |
| 7.4 Allow lecturer to manually correct recognition | Functional Specification | Section 6.4 |
| Access Control and Data Protection | Functional Specification, 3.4 | Section 3 |
| Secure File Storage | Functional Specification, 3.4 | Section 6.3 |

### 1.4 Reference Documents

| Document | Purpose |
|---|---|
| PostGrade Functional Specification | Functional requirements for recognition, validation and manual review. |
| PostGrade Technical Specification | Technical requirements SF5–SF7 and the REST API design decisions. |
| PostGrade Django Backend Onboarding Guide | Request flow and submission workflow of the current implementation. |
| GitHub Issue #2 | Persist recognition evidence and expose a stable review API. |

---

## 2. Conventions

- **Must / Shall** indicates a mandatory behaviour; **Should** a recommended behaviour; **May** an optional behaviour.
- All endpoints are relative to the API base URL, e.g. `http://127.0.0.1:8000/api/` in development.
- Request and response bodies are JSON (`application/json`) unless stated otherwise.
- Timestamps are ISO 8601 in UTC, e.g. `2026-09-24T12:23:49.081619Z`.
- Enumerated values are lowercase strings, e.g. `"needs_verification"`.
- Fields shown as `null` are nullable; fields shown as `""` or `[]` are always present and empty when not applicable.
- HTTP status codes follow RFC 9110.

---

## 3. Authentication

All endpoints in this document require an authenticated lecturer.

- Clients must send a JWT access token in the `Authorization` header:

  ```
  Authorization: Bearer <access_token>
  ```

- Tokens are obtained from `POST /api/auth/login/` and refreshed with `POST /api/auth/refresh/`.
- A lecturer can only access submissions whose assessment belongs to one of their own courses. Requests for another lecturer's submission return `404 Not Found`, not `403 Forbidden`, so that the existence of other lecturers' records is not disclosed.
- Recognition evidence and region images inherit this rule from their submission.

---

## 4. Submission States

The `status` field of a submission describes its position in the review workflow.

| Status | Meaning | Set by |
|---|---|---|
| `uploaded` | File stored; no enrollment assigned. | Upload, or `PATCH` clearing the enrollment |
| `matched` | Recognition suggested an enrollment. Requires lecturer confirmation. | Upload with outcome `matched` |
| `needs_verification` | Recognition could not identify a student. Requires lecturer review. | Upload with any outcome other than `matched` |
| `verified` | A lecturer confirmed or corrected the enrollment. | `POST /submissions/{id}/verify/` |
| `marked` | A mark was saved and the result email was generated. | `POST /submissions/{id}/mark/` |

```
uploaded
   |  automatic recognition
   +--> matched ---------------+
   |                           |  lecturer verifies
   +--> needs_verification ----+
                               v
                           verified
                               |  lecturer enters mark
                               v
                            marked
```

### 4.1 Recognition Outcome to Status Mapping

| Recognition `outcome` | Resulting `status` |
|---|---|
| `matched` | `matched` |
| `no_match` | `needs_verification` |
| `no_candidate` | `needs_verification` |
| `region_not_found` | `needs_verification` |
| `error` | `needs_verification` |

A recognition failure never causes the upload itself to fail. The file is stored, the failure is recorded as evidence, and the submission is placed in the review queue.

---

## 5. Recognition Evidence

Every time recognition runs, PostGrade stores one recognition attempt. Submission responses include the most recent attempt as the `recognition` object. Earlier attempts are retained in the database.

### 5.1 Recognition Object

| Field | Type | Description |
|---|---|---|
| `id` | integer | Recognition attempt identifier. |
| `method` | string | Recognition method: `ocr` or `bubble`. |
| `outcome` | string | Result of the attempt. See Section 5.5. |
| `processing_version` | string | Version of the recognition pipeline that produced the evidence, e.g. `ocr-1`. |
| `raw_text` | string | Text read from the student-number region, before any cleaning. OCR only. |
| `raw_candidate` | string | Student number constructed by the recogniser before class-list matching. Ambiguous positions are written as `X`. |
| `suggested_enrollment` | integer \| null | Enrollment suggested by recognition. Set to `null` if that enrollment is later removed. |
| `suggested_student_number` | string | Student number of the suggested enrollment, kept even if the enrollment is removed. |
| `confidence` | number \| null | Confidence value. Its meaning depends on `confidence_type`. |
| `confidence_type` | string | Meaning of `confidence`. See Section 5.3. |
| `column_ambiguity` | array | Per-column problems. Bubble recognition only. See Section 5.4. |
| `region` | object \| null | Location of the student-number region. See Section 5.6. |
| `region_image_url` | string \| null | Path of the protected region image, or `null` if no image was stored. |
| `quality_issues` | array | Image-quality problems detected. See Section 5.2. |
| `created_at` | string | When the attempt was recorded. |

`recognition` is `null` for submissions uploaded before recognition evidence was introduced.

### 5.2 Quality Issues

`quality_issues` lists zero or more of the following codes.

| Code | Meaning | Source |
|---|---|---|
| `blurry` | Image too blurry for reliable recognition. | SF5-FR2 |
| `rotated` | Incorrect page orientation. | SF5-FR3 |
| `cropped_section` | Student-number section partially outside the image. | SF5-FR4 |
| `missing_section` | Student-number section not present. | SF5-FR4 |

Image-quality checking is not yet implemented; the array is currently always empty.

### 5.3 Confidence Types

Confidence values of different types are not comparable and must not be compared against the same threshold.

| `confidence_type` | Meaning | Range |
|---|---|---|
| `none` | No confidence available. `confidence` is `null`. | — |
| `ocr_score` | OCR engine's recognition score for the located text line. | 0.0–1.0 |
| `bubble_margin` | Lowest, across all columns, of the contrast margin between the darkest and second-darkest bubble (SF6-FR9). | 0.0–1.0 |

### 5.4 Column Ambiguity

Bubble recognition only. Each entry identifies a column of the 8 × 10 student-number grid that could not be read unambiguously. The corresponding position in `raw_candidate` is written as `X`.

```json
{ "column": 4, "reason": "multiple" }
```

| Field | Type | Description |
|---|---|---|
| `column` | integer | Zero-based column index, left to right. |
| `reason` | string | `multiple` (more than one filled bubble, SF6-FR7), `empty` (no bubble above the fill threshold, SF6-FR8) or `unreadable` (Functional Specification 6.5). |

OCR recognition always returns an empty array.

### 5.5 Outcomes

| `outcome` | Meaning |
|---|---|
| `matched` | Exactly one enrolled student matched the candidate. |
| `no_match` | A candidate was read but did not match exactly one enrolled student. |
| `no_candidate` | The region was found but no student number could be read from it. |
| `region_not_found` | The student-number region was not found on the page. |
| `error` | Recognition failed with an internal error. |

### 5.6 Region

```json
{
  "page": 0,
  "x": 104,
  "y": 231,
  "width": 497,
  "height": 55,
  "image_width": 1600,
  "image_height": 1132
}
```

| Field | Type | Description |
|---|---|---|
| `page` | integer | Zero-based page index. Recognition currently uses the first page only. |
| `x`, `y` | integer | Top-left corner of the region, in pixels. |
| `width`, `height` | integer | Size of the region, in pixels. |
| `image_width`, `image_height` | integer | Size of the image recognition ran on, in pixels. |

Coordinates are in pixels of the image recognition ran on. For PDF uploads this is the first page rendered at 2× scale, not the PDF's own coordinate space. To overlay the region on a differently sized preview, scale by `preview_width / image_width` and `preview_height / image_height`.

---

## 6. Endpoints

### 6.1 Upload Submission

`POST /api/submissions/`

**Purpose/Description**

Uploads a marked script for an assessment and runs automatic recognition.

**Inputs**

`Content-Type: multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `assessment` | integer | Yes | Assessment the script belongs to. Must belong to one of the lecturer's courses. |
| `file` | file | Yes | JPG, JPEG, PNG or PDF. |

**Processing**

1. The request is authenticated and the assessment's ownership is checked.
2. The file is stored and a submission is created.
3. Recognition runs and one recognition attempt is stored.
4. The status is set according to Section 4.1.

**Outputs**

| Status | Description |
|---|---|
| `201 Created` | Submission created. The body is the submission with its `recognition` object. |
| `400 Bad Request` | Validation failed. See Section 7. |
| `401 Unauthorized` | Missing or invalid token. |

**Example response** — `201 Created`

```json
{
  "id": 1,
  "assessment": 1,
  "enrollment": 1,
  "file": "http://127.0.0.1:8000/media/submissions/2026/09/24/s.jpeg",
  "original_filename": "s.jpeg",
  "status": "matched",
  "recognition": {
    "id": 1,
    "method": "ocr",
    "outcome": "matched",
    "processing_version": "ocr-1",
    "raw_text": "Student number / Studentenommer: 3727 9432",
    "raw_candidate": "37279432",
    "suggested_enrollment": 1,
    "suggested_student_number": "37279432",
    "confidence": 0.9730657935142517,
    "confidence_type": "ocr_score",
    "column_ambiguity": [],
    "region": {
      "page": 0,
      "x": 104,
      "y": 231,
      "width": 497,
      "height": 55,
      "image_width": 1600,
      "image_height": 1132
    },
    "region_image_url": "/api/submissions/1/recognition-image/",
    "quality_issues": [],
    "created_at": "2026-09-24T12:23:49.081619Z"
  },
  "created_at": "2026-09-24T12:23:49.023321Z",
  "updated_at": "2026-09-24T12:23:49.023321Z"
}
```

### 6.2 List and Retrieve Submissions

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/submissions/` | All of the lecturer's submissions. |
| `GET` | `/api/submissions/{id}/` | One submission. |
| `GET` | `/api/submissions/verification-queue/` | Submissions with status `matched` or `needs_verification`, oldest first. |

**Purpose/Description**

Returns submissions with their latest recognition evidence for display in the review workspace.

**Outputs**

| Status | Description |
|---|---|
| `200 OK` | A submission object, or an array of submission objects, each with its `recognition` object. |
| `401 Unauthorized` | Missing or invalid token. |
| `404 Not Found` | (`{id}` only) The submission does not exist or belongs to another lecturer. |

List endpoints are not paginated.

### 6.3 Retrieve Region Image

`GET /api/submissions/{id}/recognition-image/`

**Purpose/Description**

Returns the cropped image of the student-number region from the submission's latest recognition attempt, for display alongside the full script during manual review (SF7-FR4).

**Inputs**

| Parameter | In | Type | Description |
|---|---|---|---|
| `id` | path | integer | Submission identifier. |

**Processing**

1. The request is authenticated and the submission's ownership is checked.
2. The latest recognition attempt is retrieved.
3. Its stored region image is returned.

**Outputs**

| Status | Content-Type | Description |
|---|---|---|
| `200 OK` | `image/png` | The region image. |
| `401 Unauthorized` | `application/json` | Missing or invalid token. |
| `404 Not Found` | `application/json` | The submission does not exist, belongs to another lecturer, or has no region image. |

Region images are not publicly accessible. The endpoint requires the `Authorization` header, so a browser client cannot use `region_image_url` directly as an `<img src>`. The client must request the image with its token and display the returned binary data, for example:

```ts
const response = await api.get(url, { responseType: 'blob' })
const src = URL.createObjectURL(response.data)
```

### 6.4 Verify Submission

`POST /api/submissions/{id}/verify/`

**Purpose/Description**

Confirms or corrects the student associated with a submission (Functional Specification 7.4). Existing endpoint; documented here because of its effect on recognition evidence.

**Inputs**

```json
{ "enrollment": 1 }
```

**Processing**

1. The enrollment must belong to the lecturer and to the submission's course.
2. A `marked` submission cannot be re-verified.
3. `enrollment` is set and `status` becomes `verified`.
4. The recognition evidence is **not** modified. `recognition.suggested_enrollment` continues to show what recognition originally suggested.

**Outputs**

| Status | Description |
|---|---|
| `200 OK` | The updated submission, including its unchanged `recognition` object. |
| `400 Bad Request` | Missing enrollment, wrong course, or submission already marked. |
| `404 Not Found` | Submission or enrollment not found for this lecturer. |

---

## 7. Error Responses

### 7.1 Format

Errors use the standard Django REST Framework format.

Non-field errors:

```json
{ "detail": "<message>" }
```

Field validation errors map each field to a list of messages:

```json
{ "<field>": ["<message>"] }
```

### 7.2 Error Catalogue

| Status | Condition | Body |
|---|---|---|
| `400` | No file in upload | `{"file": ["No file was submitted."]}` |
| `400` | Assessment belongs to another lecturer | `{"assessment": ["You cannot upload a submission for this assessment."]}` |
| `400` | Verify without enrollment | `{"detail": "Enrollment is required."}` |
| `400` | Verify with enrollment from another course | `{"detail": "Enrollment does not belong to the submission's course."}` |
| `400` | Verify a marked submission | `{"detail": "A marked submission cannot be re-verified."}` |
| `401` | No `Authorization` header | `{"detail": "Authentication credentials were not provided."}` |
| `401` | Invalid or expired token | See 7.3 |
| `404` | Submission not found or not owned | `{"detail": "No Submission matches the given query."}` |
| `404` | Submission has no region image | `{"detail": "No recognition image for this submission."}` |

### 7.3 Invalid Token

```json
{
  "detail": "Given token not valid for any token type",
  "code": "token_not_valid",
  "messages": [
    {
      "token_class": "AccessToken",
      "token_type": "access",
      "message": "Token is invalid"
    }
  ]
}
```

On `401` with `code: "token_not_valid"`, the client should refresh the access token and retry once.

### 7.4 Recognition Failures

Recognition failures are not HTTP errors. An upload whose recognition fails still returns `201 Created`; the failure is reported in `recognition.outcome` (Section 5.5) and the submission enters the review queue. Internal error details are written to the server log and are not returned to the client.

---

## 8. Recognition Examples

### 8.1 OCR — Matched

See the example in Section 6.1.

### 8.2 OCR — Region Not Found

`status` is `needs_verification`; no region or image is stored.

```json
"recognition": {
  "id": 2,
  "method": "ocr",
  "outcome": "region_not_found",
  "processing_version": "ocr-1",
  "raw_text": "",
  "raw_candidate": "",
  "suggested_enrollment": null,
  "suggested_student_number": "",
  "confidence": null,
  "confidence_type": "none",
  "column_ambiguity": [],
  "region": null,
  "region_image_url": null,
  "quality_issues": [],
  "created_at": "2026-09-24T12:23:49.097201Z"
}
```

### 8.3 OCR — Internal Error

`status` is `needs_verification`; the fields match 8.2 except:

```json
"outcome": "error"
```

### 8.4 Evidence After Lecturer Correction

After `POST /api/submissions/2/verify/` with `{"enrollment": 1}`, the submission changes but its evidence does not:

```json
{
  "id": 2,
  "enrollment": 1,
  "status": "verified",
  "recognition": {
    "id": 2,
    "outcome": "region_not_found",
    "suggested_enrollment": null
  }
}
```

(Abbreviated; all other fields are unchanged.)

### 8.5 Bubble — Multi-Mark Column (Planned Format)

Bubble recognition is not yet implemented. The following shows the evidence format a bubble implementation must produce. Column 4 has two filled bubbles, so position 4 of `raw_candidate` is `X` and the submission requires manual review.

```json
"recognition": {
  "id": 7,
  "method": "bubble",
  "outcome": "no_match",
  "processing_version": "bubble-1",
  "raw_text": "",
  "raw_candidate": "3727X432",
  "suggested_enrollment": null,
  "suggested_student_number": "",
  "confidence": 0.41,
  "confidence_type": "bubble_margin",
  "column_ambiguity": [
    { "column": 4, "reason": "multiple" }
  ],
  "region": {
    "page": 0,
    "x": 212,
    "y": 340,
    "width": 640,
    "height": 800,
    "image_width": 2480,
    "image_height": 3508
  },
  "region_image_url": "/api/submissions/7/recognition-image/",
  "quality_issues": [],
  "created_at": "2026-10-01T09:15:02.000000Z"
}
```

### 8.6 Bubble — Low Confidence with Quality Issue (Planned Format)

All columns were read, but the image is blurred and the confidence is below the review threshold.

```json
"recognition": {
  "id": 8,
  "method": "bubble",
  "outcome": "no_match",
  "processing_version": "bubble-1",
  "raw_text": "",
  "raw_candidate": "37279432",
  "suggested_enrollment": null,
  "suggested_student_number": "",
  "confidence": 0.62,
  "confidence_type": "bubble_margin",
  "column_ambiguity": [],
  "region": {
    "page": 0,
    "x": 208,
    "y": 336,
    "width": 644,
    "height": 804,
    "image_width": 2480,
    "image_height": 3508
  },
  "region_image_url": "/api/submissions/8/recognition-image/",
  "quality_issues": ["blurry"],
  "created_at": "2026-10-01T09:15:04.000000Z"
}
```

---

## 9. Compatibility and Rollout

- All changes are additive. No existing field, endpoint or status value was renamed or removed; existing clients continue to work unchanged.
- New submission field: `recognition`.
- New endpoint: `GET /api/submissions/{id}/recognition-image/`.
- Submissions uploaded before this release have `recognition: null`. Clients must handle this value.
- The database change is a single new table (`submissions_recognitionattempt`, migration `0004_recognitionattempt`). No existing data is modified and no backfill is required.
- `processing_version` must be changed whenever the recognition pipeline's behaviour changes, so that evidence produced by different versions can be distinguished.

---

## 10. Issues List

| ID | Description | Status |
|---|---|---|
| 01 | The Technical Specification requires errors to include a machine-readable code. Current errors use the default DRF format without a code (Section 7.1). Depends on Technical Specification Issue 01. | TBD |
| 02 | `no_match` does not distinguish "student not found" from "ambiguous match" (SF7-FR2). Requires the matching step to report its reason. | TBD |
| 03 | Duplicate-match detection across a batch (SF7-FR3) is not yet recorded in evidence. | TBD |
| 04 | Bubble recognition must not auto-match a `raw_candidate` containing `X`: the current fuzzy matching tolerates one differing character and could otherwise match it. | TBD |
| 05 | Minimum confidence threshold for automatic matching is undefined (Technical Specification Issue 04; SF6-FR10 proposes 85% for `bubble_margin`). | TBD |
| 06 | The `file` URL returned on submissions points to `/media/`, which is not served. A protected full-script preview endpoint is required for the review workspace. | TBD |
| 07 | Image-quality checking (SF5) is not implemented; `quality_issues` is always empty. | TBD |
