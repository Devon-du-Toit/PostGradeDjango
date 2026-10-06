# PostGrade API reference

Current script-only workflow: upload → recognise → verify → email script. Numeric grading has been removed. All paths below include `/api/`; use JWT `Authorization: Bearer <access_token>` for protected routes.

## Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/register/` | Create an account using email, password, first_name, last_name |
| POST | `auth/login/` | Obtain access and refresh tokens using email/password |
| POST | `auth/refresh/` | Rotate access/refresh pair; old refresh is revoked |
| POST | `auth/logout/` | Revoke the supplied refresh token |
| GET | `auth/registration-policy/` | Public registration_open boolean |
| GET | `auth/me/` | Current account |

Normal data endpoints are owner-scoped. Another owner's detail/action returns 404; invalid/other-owner related-object selections return 400. Role labels do not grant delegated course access. Registration does not accept an elevated role. Signup availability, client throttles, token expiry/revocation and deployment order are documented in [PERMISSIONS.md](PERMISSIONS.md).

## Courses, class lists and students

| Methods | Path | Purpose |
|---|---|---|
| GET POST | `courses/` | Owned active courses; code, name, year, semester |
| GET PUT PATCH DELETE | `courses/{id}/` | Read/edit; DELETE archives |
| GET | `courses/{id}/students/` | Active course class list |
| POST | `courses/{id}/import-students/` | Multipart CSV file, validated update_existing/dry_run booleans; 409 if the plan becomes stale |
| GET POST | `students/` | Owned contacts |
| GET PUT PATCH DELETE | `students/{id}/` | Owned contact; DELETE is physical deletion |
| POST | `students/{id}/email/` | Direct subject/message text email, separate from script delivery |
| GET POST | `enrollments/` | Owned active course enrollments; course, student |

CSV previews and updates are defined in [CSV_IMPORT_AND_LIFECYCLE.md](CSV_IMPORT_AND_LIFECYCLE.md). Imports are additive and atomic; malformed records return physical starting line numbers, and no student details change without update_existing=true.

CSV columns: `student_number,first_name,last_name,email`. Student numbers are strings; retain leading zeros. Defaults: UTF-8 with optional BOM, 2 MB, 5000 rows. Validation precedes atomic application. `dry_run=true` writes nothing; `update_existing=true` explicitly updates stored contact details. Enrollment list records include read-only student_number, first_name and last_name, so verification does not need a gradebook. There is no enrollment withdrawal/delete endpoint.

## Assessments

| Methods | Path | Purpose |
|---|---|---|
| GET POST | `courses/{id}/assessments/` | List/create name and optional date |
| GET PUT PATCH DELETE | `assessments/{id}/` | Read/edit; DELETE archives |

Create: `{"name":"Test 1","date":"2026-10-06"}`. Responses contain id, course, name, date, created_at, updated_at. Scoring inputs `mark`, `max_mark` and `weight` return 400. There is no results, gradebook or numeric statistics endpoint.

## Submissions and recognition

| Methods | Path | Purpose |
|---|---|---|
| GET POST | `submissions/` | Filter owned scripts / upload multipart assessment, file, recognition_method |
| GET PATCH DELETE | `submissions/{id}/` | Read, replace file with current version, or delete |
| GET | `submissions/recognition-methods/` | Available recognition methods/templates |
| GET | `submissions/verification-queue/` | Matched and needs_verification scripts |
| POST | `submissions/{id}/verify/` | Enrollment ID from the assessment's course |
| POST | `submissions/{id}/retry-recognition/` | Retry eligible recognition preserving its method |
| GET | `submissions/{id}/file/` | Protected original file |
| GET | `submissions/{id}/recognition-image/` | Protected latest evidence crop |
| POST | `submissions/{id}/email/` | Explicit verified-script delivery request |

Uploads accept validated PDF, JPG/JPEG and PNG; defaults: 15 MB, 20 PDF pages, 6000 pixels per image dimension. Empty/corrupt/encrypted/type-mismatched files are rejected. Files are stored, recognition is queued, and the request does not wait for OCR.

`recognition_method` is `ocr` (default) or `bubble`. Bubbles read fills only and suggest a student only for eight clear columns with an exact enrollment match in this class. Both methods need lecturer confirmation. See [BUBBLE_RECOGNITION.md](BUBBLE_RECOGNITION.md) and [RECOGNITION_EVIDENCE_API.md](RECOGNITION_EVIDENCE_API.md).

States: uploaded, processing, matched, needs_verification, recognition_failed, verified. Delivery state is separate. A failed recognition can be verified manually on the assessment page; the global queue currently includes only matched and needs_verification.

Verification is transactional and repeating the same verified enrollment is idempotent. Send `version` on verification/retry to reject stale reviews. Changing a verified student requires `POST submissions/{id}/correct/` with enrollment, current version and nonblank reason. See [SUBMISSION_TRANSITIONS.md](SUBMISSION_TRANSITIONS.md). File replacement requires `version`, resets enrollment/status, increments version and supersedes unsent mail. Generic edits cannot change the assessment or student. No raw public media path is returned; use protected download_url and evidence routes.

## Script emails

| Method | Path | Purpose |
|---|---|---|
| GET | `assessments/{id}/script-emails/` | Filter/search delivery history |
| GET | `script-emails/{id}/` | Stored preview/delivery state |
| POST | `script-emails/{id}/approve/` | Approve one awaiting current delivery |
| POST | `assessments/{id}/script-emails/approve/` | Approve current awaiting deliveries |
| POST | `script-emails/{id}/retry/` | Retry failed current delivery; explicit boolean confirm_duplicate for unknown delivery |

Every requested email includes a private snapshot of the verified script. Requests are idempotent per submission/version; sent records cannot be resent using retry. States: awaiting_approval, queued, sending, sent, failed, superseded. See [SCRIPT_EMAIL_DELIVERY.md](SCRIPT_EMAIL_DELIVERY.md) for policy, attachments, worker leases and retries.

## Dashboard and lists

GET `dashboard/stats/`: active_courses in the current calendar year, pending_verifications, and submissions_by_status. GET `dashboard/assessments/`: paginated active assessment progress, with course/name/date, enrolled, submissions and submissions_by_status. No numeric results fields remain.

Lists use count/next/previous/results with page size 25, maximum 100. Filters and search run before pagination; ordering includes an ID tie-breaker. Course filters: year/semester; student/enrollment filters: course/student; submissions: course/assessment/status; email records: status. See [API_CONTRACT.md](API_CONTRACT.md).

## Archiving, errors and rollout

Archiving retains files and delivery/audit history, hides related records from active APIs, cancels recognition and supersedes unsent script mail. Archived actions/downloads return 404. See [ARCHIVING.md](ARCHIVING.md).

400: invalid data/filter/state; 401: missing/expired credentials; 404: absent, archived, other-owner object, removed route, or page beyond end. Mail failure does not undo verification; inspect delivery status separately.

The former submission mark, results, gradebook, statistics and result-email routes are removed. Deploy the matching Vue change and follow [MARKS_REMOVAL.md](MARKS_REMOVAL.md), including backup before the numeric-data deletion migration. No automatic legacy delivery backfill runs.
