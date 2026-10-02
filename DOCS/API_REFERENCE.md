# API Reference — Architecture and Endpoint Inventory

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-09-30 | @CiViCDottir | Initial version (issue #15) |

## Table of Contents

1. [Introduction](#1-introduction)
2. [Architecture](#2-architecture)
3. [Conventions](#3-conventions)
4. [Authentication (`/api/auth/`)](#4-authentication-apiauth)
5. [Courses (`/api/courses/`)](#5-courses-apicourses)
6. [Students and Enrollments (`/api/students/`, `/api/enrollments/`)](#6-students-and-enrollments-apistudents-apienrollments)
7. [Assessments and Results (`/api/assessments/`, `/api/results/`)](#7-assessments-and-results-apiassessments-apiresults)
8. [Submissions and Recognition](#8-submissions-and-recognition)
9. [Result Email Delivery](#9-result-email-delivery)
10. [Data Lifecycle and Operations](#10-data-lifecycle-and-operations)
11. [Error Response Conventions](#11-error-response-conventions)
12. [Related Resources](#12-related-resources)
13. [Issues List](#13-issues-list)

---

## 1. Introduction

### 1.1 Purpose

This document is the entry point for understanding PostGrade's
backend API. It covers the architecture shared by every app, and
gives a full endpoint inventory — with synthetic request/response
examples — for the four apps that had never been documented at the
API level: **accounts, courses, students, and assessments**.

### 1.2 Scope

This document intentionally does **not** duplicate documentation
that already exists elsewhere in `DOCS/`. Submissions, recognition,
email delivery, and backup/restore each already have their own
detailed, dedicated document (linked in
[§12 Related Resources](#12-related-resources)); this document
covers those areas only at a high level and points to the detailed
docs for anything beyond that.

### 1.3 Requirement Traceability

Written to close issue #15 ("Update backend documentation and API
examples for current workflows"), created from the PostGrade
development review on 2026-09-14.

### 1.4 A note on timing

At the time of writing, PR #22 (submission file validation,
authorized downloads, and storage lifecycle) has **not yet been
merged**. Section 8 documents the submission API as it exists on
`master` today. Once #22 merges, this document (and
`RECOGNITION_EVIDENCE_API.md`) will need a follow-up update to
describe the new authorized file-download endpoint and the
replacement/deletion behaviour it introduces. This is a recorded,
known gap — not an oversight.

---

## 2. Architecture

Every request to this API follows the same path, regardless of
which app handles it:

```
Client (Vue frontend, or any API consumer)
  | HTTP + JSON, JWT Bearer token
  v
Django URL routing (config/urls.py)
  v
App-level URL routing (e.g. courses/urls.py)
  v
DRF View (validates permissions, orchestrates the request)
  v
Serializer (validates input, shapes output)
  v
Model / service layer (business rules, database access)
  v
PostgreSQL
  v
JSON response
```

### 2.1 App inventory

| App | Owns | Status |
|---|---|---|
| `accounts` | Users, JWT authentication | Documented in §4 |
| `courses` | Course records | Documented in §5 |
| `students` | Students, enrollments, CSV import | Documented in §6 |
| `assessments` | Assessments, results, gradebook, statistics | Documented in §7 |
| `submissions` | Uploaded scripts, OCR recognition, verification | Summarized in §8; full detail in `RECOGNITION_EVIDENCE_API.md` and `RECOGNITION_WORKER.md` |
| `distribution` | Result email delivery | Summarized in §9; full detail in `RESULT_EMAIL_DELIVERY.md` |

### 2.2 The ownership pattern

Almost every queryset in this codebase is filtered by ownership —
either `owner=request.user` directly, or by walking a relationship
to reach the owning user (e.g. `course__owner=request.user`). This
is the core authorization mechanism throughout the API: a lecturer
can only ever see and modify their own courses, students,
assessments, and submissions. When adding a new endpoint, preserve
this pattern.

---

## 3. Conventions

- **Base path:** all endpoints below are relative to `/api/`.
- **Format:** all requests and responses use JSON, except file
  uploads (`multipart/form-data`) and file downloads.
- **Authentication:** every endpoint except `register`, `login` and
  `refresh` requires a JWT access token (see §4). `refresh` takes the
  refresh token in the request body, so it works without an access
  token.
- **Pagination:** list endpoints are **not paginated** — they
  return a plain JSON array of every matching object. This is worth
  knowing if a course ever has a very large number of students or
  submissions.
- **Examples use synthetic data only.** No email address, name, or
  student number in this document corresponds to a real person.

---

## 4. Authentication (`/api/auth/`)

| Method | Endpoint | Auth required | Purpose |
|---|---|---|---|
| `POST` | `/api/auth/register/` | No | Create a user |
| `POST` | `/api/auth/login/` | No | Obtain JWT access + refresh tokens |
| `POST` | `/api/auth/refresh/` | No (refresh token) | Obtain a new access token |
| `GET` | `/api/auth/me/` | Yes | Return the authenticated user |

PostGrade uses a custom user model with **email as the login field**
(no username). Every user has a `role`: `ADMIN`, `LECTURER`, or
`MARKER` — but as of this writing, API authorization is based on
**ownership**, not role; the role field is not yet used to restrict
access to specific endpoints.

### 4.1 Register

**Request**
```http
POST /api/auth/register/
Content-Type: application/json

{
  "email": "lecturer1@example.edu",
  "first_name": "Ada",
  "last_name": "Lovelace",
  "password": "a-strong-password-123"
}
```

**Response — `201 Created`**
```json
{
  "id": 4,
  "email": "lecturer1@example.edu",
  "first_name": "Ada",
  "last_name": "Lovelace"
}
```

### 4.2 Login

**Request**
```http
POST /api/auth/login/
Content-Type: application/json

{
  "email": "lecturer1@example.edu",
  "password": "a-strong-password-123"
}
```

**Response — `200 OK`**
```json
{
  "refresh": "eyJhbGciOi...",
  "access": "eyJhbGciOi..."
}
```

Every subsequent request must include the access token:
```http
Authorization: Bearer eyJhbGciOi...
```

### 4.3 Current user

**Request**
```http
GET /api/auth/me/
Authorization: Bearer eyJhbGciOi...
```

**Response — `200 OK`**
```json
{
  "id": 4,
  "email": "lecturer1@example.edu",
  "first_name": "Ada",
  "last_name": "Lovelace",
  "role": "LECTURER"
}
```

---

## 5. Courses (`/api/courses/`)

A course belongs to exactly one lecturer (`owner`). Uniqueness is
enforced on `(owner, code, year, semester)` — the same lecturer
cannot create two courses with the same code in the same
year/semester.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/courses/` | List the authenticated user's courses |
| `POST` | `/api/courses/` | Create a course (owner is set automatically) |
| `GET` | `/api/courses/<id>/` | Retrieve one course |
| `PUT`/`PATCH` | `/api/courses/<id>/` | Update a course |
| `DELETE` | `/api/courses/<id>/` | Delete a course (cascades to its assessments, enrollments, and submissions) |
| `GET` | `/api/courses/<course_id>/students/` | List students enrolled in this course |
| `POST` | `/api/courses/<course_id>/import-students/` | Bulk-import students from a CSV file |

### 5.1 Create a course

**Request**
```http
POST /api/courses/
Authorization: Bearer <token>
Content-Type: application/json

{
  "code": "CSC201",
  "name": "Data Structures and Algorithms",
  "year": 2026,
  "semester": 2
}
```

**Response — `201 Created`**
```json
{
  "id": 12,
  "code": "CSC201",
  "name": "Data Structures and Algorithms",
  "year": 2026,
  "semester": 2,
  "created_at": "2026-09-30T09:00:00Z",
  "updated_at": "2026-09-30T09:00:00Z"
}
```

**Known gap — duplicate course currently returns `500`, not `400`.**
Verified directly against the code: creating a duplicate course for
the same owner/code/year/semester raises an unhandled
`django.db.utils.IntegrityError`, which surfaces as a raw
`500 Internal Server Error` rather than a clean validation message.
`CourseSerializer` does not declare a `UniqueTogetherValidator`
matching the model's database constraint, so Django REST Framework
never gets a chance to catch this before it reaches the database.
This is a real bug worth its own follow-up issue, not a
documentation gap — flagging it here rather than describing
behaviour that doesn't actually exist.

### 5.2 CSV student import

**The CSV format** (this was previously undocumented anywhere in
the project):

- Must be a genuine `.csv` file, sent as `multipart/form-data` under
  the field name `file`.
- Required header columns, in any order:
  `student_number,first_name,last_name,email`
- One student per row.

**Example file — `roster.csv`**
```csv
student_number,first_name,last_name,email
20261001,Naledi,Dlamini,naledi.dlamini@example.edu
20261002,Thabo,Mokoena,thabo.mokoena@example.edu
20261003,Aisha,Khan,aisha.khan@example.edu
```

**Request**
```http
POST /api/courses/12/import-students/
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: roster.csv
```

**Response — `200 OK`**
```json
{
  "message": "Students imported successfully."
}
```

**Import behaviour, worth knowing:**
- If a student with the same `student_number` already exists for
  this lecturer, the existing student record is reused (matched by
  `owner` + `student_number`) rather than duplicated — only a new
  `Enrollment` linking them to this course is created.
- If a student with that number doesn't exist yet, a new `Student`
  record is created.
- The whole import runs inside a single database transaction: if
  **any** row fails validation, the **entire** import is rolled
  back — no partial imports.

**Error — `400 Bad Request`** (missing required column)
```json
{
  "file": "Missing required columns: email"
}
```

**Error — `400 Bad Request`** (a specific row fails validation —
e.g. malformed email)
```json
{
  "row": 2,
  "errors": {
    "email": ["Enter a valid email address."]
  }
}
```
(`row` counts the header as row 1, so `2` is the *first* data row —
matching what a lecturer would see if they opened the CSV in a
spreadsheet program, where row 1 is the header.)

---

## 6. Students and Enrollments (`/api/students/`, `/api/enrollments/`)

A `Student` belongs to one lecturer (`owner`). An `Enrollment` links
a `Student` to a `Course` — both must belong to the same lecturer.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/students/` | List the authenticated user's students |
| `POST` | `/api/students/` | Create a student manually |
| `GET` | `/api/students/<id>/` | Retrieve one student |
| `PUT`/`PATCH` | `/api/students/<id>/` | Update a student |
| `DELETE` | `/api/students/<id>/` | Delete a student |
| `POST` | `/api/students/<id>/email/` | Send a free-text email to this student |
| `GET` | `/api/enrollments/` | List the authenticated user's enrollments |
| `POST` | `/api/enrollments/` | Enroll a student in a course |

### 6.1 Create a student

**Request**
```http
POST /api/students/
Authorization: Bearer <token>
Content-Type: application/json

{
  "student_number": "20261004",
  "first_name": "Farai",
  "last_name": "Chiweshe",
  "email": "farai.chiweshe@example.edu"
}
```

**Response — `201 Created`**
```json
{
  "id": 45,
  "student_number": "20261004",
  "first_name": "Farai",
  "last_name": "Chiweshe",
  "email": "farai.chiweshe@example.edu",
  "created_at": "2026-09-30T09:05:00Z",
  "updated_at": "2026-09-30T09:05:00Z"
}
```

### 6.2 Enroll a student

**Request**
```http
POST /api/enrollments/
Authorization: Bearer <token>
Content-Type: application/json

{
  "course": 12,
  "student": 45
}
```

**Response — `201 Created`**
```json
{
  "id": 88,
  "course": 12,
  "student": 45,
  "created_at": "2026-09-30T09:06:00Z"
}
```

**Error — `400 Bad Request`** (enrolling a student that belongs to
a different lecturer)
```json
{
  "student": ["You cannot enroll this student."]
}
```

### 6.3 Email a student

Sends a free-text email directly (separate from the automated
result-delivery emails covered in §9).

**Request**
```http
POST /api/students/45/email/
Authorization: Bearer <token>
Content-Type: application/json

{
  "subject": "Missing submission for Test 2",
  "message": "Hi Farai, we don't have a submission from you for Test 2. Please see me during office hours."
}
```

**Response — `200 OK`**
```json
{
  "detail": "Email sent."
}
```

---

## 7. Assessments and Results (`/api/assessments/`, `/api/results/`)

An `Assessment` belongs to one `Course` and defines `max_mark` and
`weight` (used in the weighted course-grade calculation). A `Result`
links one `Enrollment` to one `Assessment` and stores a `mark`,
which cannot exceed the assessment's `max_mark`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`/`POST` | `/api/courses/<course_id>/assessments/` | List/create assessments for a course |
| `GET`/`PUT`/`PATCH`/`DELETE` | `/api/assessments/<id>/` | Manage one assessment |
| `GET`/`POST` | `/api/assessments/<assessment_id>/results/` | List/create results for an assessment |
| `GET`/`PUT`/`PATCH`/`DELETE` | `/api/results/<id>/` | Manage one result |
| `GET` | `/api/courses/<course_id>/gradebook/` | Full gradebook for a course |
| `GET` | `/api/assessments/<id>/statistics/` | Aggregate statistics for one assessment |

### 7.1 Create an assessment

**Request**
```http
POST /api/courses/12/assessments/
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Test 2",
  "max_mark": "50.00",
  "weight": "15.00",
  "date": "2026-10-15"
}
```

**Response — `201 Created`**
```json
{
  "id": 30,
  "course": 12,
  "name": "Test 2",
  "max_mark": "50.00",
  "weight": "15.00",
  "date": "2026-10-15",
  "created_at": "2026-09-30T09:10:00Z",
  "updated_at": "2026-09-30T09:10:00Z"
}
```

### 7.2 Record a result

**Request**
```http
POST /api/assessments/30/results/
Authorization: Bearer <token>
Content-Type: application/json

{
  "enrollment": 88,
  "mark": "42.00"
}
```

**Response — `201 Created`**
```json
{
  "id": 61,
  "assessment": 30,
  "enrollment": 88,
  "student_number": "20261004",
  "student_name": "Farai Chiweshe",
  "mark": "42.00",
  "percentage": 84.0,
  "created_at": "2026-09-30T09:12:00Z",
  "updated_at": "2026-09-30T09:12:00Z"
}
```

**Error — `400 Bad Request`** (mark exceeds max_mark)
```json
{
  "mark": ["Mark cannot exceed the assessment's maximum mark."]
}
```

**Note:** editing a `Result` that has already had a result email
sent to the student automatically triggers a **corrected** email
(see §9) — a `Result` also carries a `version` number, incremented
on every mark change, which the email system uses to avoid sending
duplicate or stale notifications.

### 7.3 Gradebook

**Request**
```http
GET /api/courses/12/gradebook/
Authorization: Bearer <token>
```

**Response — `200 OK`**
```json
{
  "course": 12,
  "students": [
    {
      "enrollment": 88,
      "student": 45,
      "student_number": "20261004",
      "first_name": "Farai",
      "last_name": "Chiweshe",
      "assessments": [
        {
          "assessment": 30,
          "name": "Test 2",
          "mark": "42.00",
          "max_mark": "50.00",
          "percentage": "84.0000",
          "weight": "15.00"
        }
      ],
      "course_percentage": "84.00"
    }
  ]
}
```

`mark` and `percentage` are `null` for any assessment the student
hasn't been marked for yet. `course_percentage` is a weighted
average across only the assessments that **do** have a recorded
result — an ungraded assessment does not count against a student.

**Known inconsistency, verified directly:** the per-assessment
`percentage` here is **not rounded** (`"84.0000"`, four decimal
places) because `CourseGradebookView` computes it manually with raw
Decimal division and no `.quantize()` call. This differs from
`ResultSerializer.get_percentage()` (§7.2), which explicitly rounds
to 2 decimal places. Both values are mathematically correct — this
is a formatting inconsistency between two different code paths, not
a bug in the calculation itself, but worth knowing if the frontend
displays both figures side by side.

### 7.4 Assessment statistics

**Request**
```http
GET /api/assessments/30/statistics/
Authorization: Bearer <token>
```

**Response — `200 OK`**
```json
{
  "assessment": 30,
  "name": "Test 2",
  "graded_count": 1,
  "average_percentage": "84.00",
  "minimum_percentage": "84.00",
  "maximum_percentage": "84.00"
}
```

---

## 8. Submissions and Recognition

The submissions app is where uploaded scripts go through automated
student-number recognition, human verification, and marking. It has
grown substantially and is **documented separately and in depth**:

- **`DOCS/RECOGNITION_EVIDENCE_API.md`** — every submission
  endpoint, the full recognition-outcome catalogue, quality-check
  thresholds, confidence types, and error responses. Includes an
  explicit, honest note that **bubble-sheet recognition is a
  planned format, not yet implemented** — only OCR-based recognition
  currently runs.
- **`DOCS/RECOGNITION_WORKER.md`** — how the background recognition
  worker works, local setup, retry/crash-recovery behaviour, and
  troubleshooting.

### 8.1 Submission status lifecycle (summary)

```
uploaded → processing → matched ────────┐
                      ↘ needs_verification │
                                           ├→ verified → marked
recognition_failed ←──(retry)─────────────┘
```

A submission enters `processing` the moment it's uploaded; a
background worker (see `RECOGNITION_WORKER.md`) then attempts
automatic recognition. If recognition can't confidently identify a
student, the submission is deliberately routed to
`needs_verification` for a human to resolve — the system never
guesses.

### 8.2 Known gap: PR #22 (in progress)

As of this writing, `master` does **not** yet include:
- Content/size validation on uploaded files
- An authorized, ownership-checked download endpoint for the
  original file
- Deletion-triggered storage cleanup, or a decision on file
  replacement

These are all part of PR #22, still under review. Once merged, this
section and `RECOGNITION_EVIDENCE_API.md` should be updated together
to describe the new download endpoint and replacement policy.

---

## 9. Result Email Delivery

Sending a student their mark is handled asynchronously by the
`distribution` app, with its own background mail worker. Fully
documented in **`DOCS/RESULT_EMAIL_DELIVERY.md`**, including retry
behaviour, how edited marks trigger a corrected email, and the full
API for inspecting delivery status.

---

## 10. Data Lifecycle and Operations

- **Database backup and restore** is documented in
  **`DOCS/BACKUP_RESTORE.md`**.
- **Submission file retention** (how long uploaded files are kept,
  and what happens to storage when a submission is deleted) is
  being defined as part of PR #22 — see §8.2. Until that merges,
  there is no automatic cleanup of submission files anywhere in the
  codebase.
- **Running tests:**
  ```bash
  python manage.py test              # full suite
  python manage.py test submissions  # one app
  python manage.py check
  python manage.py makemigrations --check
  ```

---

## 11. Error Response Conventions

Across all apps in this document (accounts, courses, students,
assessments), validation errors follow Django REST Framework's
default shape: a JSON object whose keys are the field names that
failed, each mapping to a list of human-readable messages.
Non-field errors (e.g. a uniqueness constraint spanning several
fields) appear under `"non_field_errors"`.

```json
{
  "field_name": ["What was wrong with this field."],
  "non_field_errors": ["A problem that isn't tied to one field."]
}
```

`submissions` and `distribution` follow a similar shape but with
some endpoint-specific extensions — see their dedicated docs for
the full error catalogue.

Common HTTP status codes used throughout:

| Status | Meaning in this API |
|---|---|
| `200 OK` | Successful GET, or a successful action returning data |
| `201 Created` | Successful POST that created something |
| `400 Bad Request` | Validation failed |
| `401 Unauthorized` | Missing or invalid JWT token |
| `404 Not Found` | Object doesn't exist, **or** exists but belongs to a different user (deliberate — see §2.2) |

---

## 12. Related Resources

| Document | Covers |
|---|---|
| `DOCS/POSTGRESQL_SETUP.md` | Local database setup |
| `DOCS/RECOGNITION_EVIDENCE_API.md` | Full submission/recognition API, quality checks, bubble format (planned) |
| `DOCS/RECOGNITION_WORKER.md` | Background recognition worker setup and troubleshooting |
| `DOCS/RESULT_EMAIL_DELIVERY.md` | Async result email delivery |
| `DOCS/BACKUP_RESTORE.md` | Database backup and recovery |
| `DOCS/CI.md`, `DOCS/DB_REVIEW.md` | CI pipeline and database review notes |
| [PostGradeVue repository](https://github.com/Devon-du-Toit/PostGradeVue) | The Vue.js frontend that consumes this API |
| README's [Development Roadmap](../README.md#development-roadmap) | Where the project is headed |

---

## 13. Issues List

| Issue | Status |
|---|---|
| #15 | This document — architecture and endpoint inventory for accounts, courses, students, assessments |
| #22 | Submission file validation and authorized downloads — pending; see §8.2 |
