# Result Email Delivery

PostGrade — Group 13

Version 0.1.0

## Revision History

| Date | Version | Description | Author |
|---|---|---|---|
| 24/09/2026 | 0.1.0 | Result emails decoupled from saving marks: outbox records, mail worker, release policy and delivery API (Issue #7). | Graham Robert |

## Table of Contents

1. [Introduction](#1-introduction)
2. [Decisions](#2-decisions)
3. [How It Works](#3-how-it-works)
4. [Local Setup](#4-local-setup)
5. [Delivery States](#5-delivery-states)
6. [Reliability Behaviour](#6-reliability-behaviour)
7. [API](#7-api)
8. [Error Responses](#8-error-responses)
9. [Configuration](#9-configuration)
10. [Compatibility](#10-compatibility)
11. [Issues List](#11-issues-list)

---

## 1. Introduction

### 1.1 Purpose

This document describes how PostGrade delivers result emails to students after a lecturer saves a mark, and the API through which lecturers review, approve and retry those emails.

### 1.2 Background

Previously, `POST /api/submissions/{id}/mark/` saved the result, set the submission to `marked` and then sent the email inside the same request. A mail failure could therefore occur after the mark had already been saved, and the lecturer received an error for an operation that had partly succeeded.

The mark and a **result email record** are now saved together in one database transaction. A separate **mail worker** sends the email afterwards. A mail problem can no longer affect a saved mark, and every email has a trackable status.

### 1.3 Requirement Traceability

| Requirement | Source | Addressed by |
|---|---|---|
| Mail Dispatch Worker retrieves approved deliveries and sends asynchronously | Technical Specification, Component Interaction | Sections 3, 4 |
| 10.3 Send the correct script to the correct student | Functional Specification | Section 6.5 |
| 10.4 Track email sending status | Functional Specification | Sections 5, 7.1 |
| 10.5 Retry failed email deliveries | Functional Specification | Sections 6.1, 7.4 |
| 10.7 Preview email before sending | Functional Specification | Sections 2.1, 7.1 |
| 10.8 Send all approved scripts with one click | Functional Specification | Section 7.3 |
| SF10-FR7 Automatic retry with exponential backoff, maximum 3 attempts | Technical Specification | Section 6.1 |
| Data Integrity: duplicate distributions require explicit confirmation | Functional Specification, 2.6 | Section 6.3 |
| Logging and Error Protection | Functional Specification, 3.4 | Section 7.1 (`failure_reason`) |

### 1.4 Reference Documents

| Document | Purpose |
|---|---|
| PostGrade Functional Specification | Email distribution requirements (Section 10). |
| PostGrade Technical Specification | System Feature 10 and the Mail Dispatch Worker. |
| GitHub Issue #7 | Decouple result email delivery from saving marks. |

---

## 2. Decisions

The ticket requires the release policy to be decided before it is implemented, and unresolved scope to be recorded.

### 2.1 Release Policy

**Decision:** both policies are supported, selected by the `RESULT_EMAIL_RELEASE_POLICY` setting. The default is **`automatic`**.

| Policy | Behaviour | Rationale |
|---|---|---|
| `automatic` (default) | Saving a mark queues the email immediately. | Preserves the existing behaviour, which the current frontend depends on: it has no approval screen. |
| `approval` | Saving a mark creates the email in `awaiting_approval`. It is sent only after a lecturer approves it, individually or for a whole assessment. | Matches the Functional Specification's requirement that distribution is approved by the lecturer. Requires the approval screen described in Issue 01. |

In both policies, the exact recipient, subject and body are stored when the mark is saved and can be reviewed through the API before and after sending.

### 2.2 Which Changes Send an Email

| Action | Email |
|---|---|
| `POST /api/submissions/{id}/mark/` | Always scheduled. |
| `PATCH /api/results/{id}/` on a result that already has a result email | A corrected email is scheduled for the new mark. |
| `POST` / `PATCH` on results that have never been emailed (gradebook entry) | None. Existing behaviour is unchanged. |

### 2.3 Crashes During Sending

**Decision:** an email whose worker stopped mid-send is **not** resent automatically. It is marked `failed` with reason `delivery_unknown`, and a lecturer must explicitly confirm a resend. This follows the Functional Specification: duplicate distributions require explicit confirmation.

---

## 3. How It Works

### 3.1 Components

| Component | Where it runs | Responsibility |
|---|---|---|
| Web server | `python manage.py runserver` | Saves the mark and the result email record in one transaction. |
| Outbox | `distribution_resultemail` table in PostgreSQL | One row per result version. Rows with status `queued` are waiting to be sent. |
| Mail worker | `python manage.py run_mail_worker` | Claims queued emails and sends them through Django's configured email backend. |

### 3.2 Flow

```
Vue ──POST /submissions/{id}/mark/──▶ web server
                                        1. save result (version N)          ─┐
                                        2. set submission to marked           │ one transaction
                                        3. create result email (queued)      ─┘
                                     ◀── 201 Created, with email_delivery

                                      outbox (PostgreSQL)
                                              │
                                      mail worker: claim → check version → send → sent
```

### 3.3 Result Versions and Idempotency

Every `Result` has a `version`, starting at 1 and incremented whenever its mark changes. Saving the same mark again does not change the version.

Each result email is identified by an **idempotency key** built from the result and its version, for example `result-12-v2`. The key is unique in the database, so:

- A repeated request for the same mark reuses the existing email.
- A changed mark produces a new version, and therefore a new email.
- The key is also used as the email's `Message-ID`, so a confirmed resend of the same email is recognisable as a repeat by mail clients.

---

## 4. Local Setup

The mail worker runs alongside the development server, in its own terminal:

Terminal 1:

```bash
python manage.py runserver
```

Terminal 2:

```bash
python manage.py run_mail_worker
```

Expected output:

```
Mail worker started.
```

With the default console email backend, sent emails are printed in the mail worker's terminal (not the web server's).

Press `Ctrl+C` to stop. The worker finishes the email it is sending, then exits.

Options:

| Option | Default | Description |
|---|---|---|
| `--poll-interval` | `2.0` | Seconds to wait before checking again when nothing is queued. |
| `--once` | off | Send every email that is currently due, then exit. |

Without a running mail worker, marks are saved normally and emails remain `queued` until a worker starts.

---

## 5. Delivery States

```
                 ┌─────── approval policy ───────┐
mark saved ──────┤                               ▼
                 │                        awaiting_approval ──approve──┐
                 └── automatic policy ──────────────────────────────▶ queued ◀── lecturer retry
                                                                       │            ▲
                                                             claim     ▼            │
                                                                    sending ────────┤
                                                                       │            │
                                                     ┌─────────────────┼────────────┤
                                                     ▼                 ▼            │
                                                   sent             failed ─────────┘
any unsent state ──(mark changed)──▶ superseded
```

| Status | Meaning |
|---|---|
| `awaiting_approval` | Waiting for the lecturer to approve (approval policy only). |
| `queued` | Waiting for the mail worker, or waiting until `run_after` to retry. |
| `sending` | A worker is sending it. |
| `sent` | Accepted by the mail server. |
| `failed` | Not sent. See `failure_reason`. |
| `superseded` | The mark changed before this email was sent. It will never be sent; the email for the new mark replaces it. |

| `failure_reason` | Meaning | Retried automatically |
|---|---|---|
| `missing_recipient` | The student has no email address. | No. Add the address, then retry. |
| `recipient_refused` | The mail server rejected the address. | No. |
| `provider_error` | The mail server could not be reached or returned an error. | Yes, until attempts run out. |
| `delivery_unknown` | The worker stopped while sending. The student may or may not have received it. | No. Retry requires confirmation. |

---

## 6. Reliability Behaviour

### 6.1 Retries

Mail server errors are retried with increasing delays, up to three attempts in total:

| Attempt | On failure |
|---|---|
| 1 | Retried after 1 minute |
| 2 | Retried after 4 minutes |
| 3 | `failed`, `provider_error` |

A failure affects only that email. Other emails continue to be sent.

### 6.2 Edited Marks

If a mark changes before its email is sent, the old email becomes `superseded` and is never sent; only the email with the current mark is sent. If the old email was already sent, the student receives a second email with the corrected mark.

The worker checks the result's version immediately before sending, so an email scheduled for an older mark is not sent even if the mark changes while the email is waiting.

### 6.3 Duplicates

| Situation | Behaviour |
|---|---|
| The mark endpoint is called twice | The submission row is locked. The second request waits, sees the submission is already `marked`, and is rejected. One email. |
| The same mark is saved again | The version does not change; the existing email is reused. |
| Two mail workers run at once | Each email is claimed by exactly one worker (`SELECT … FOR UPDATE SKIP LOCKED`). |
| A worker stops mid-send | The email becomes `delivery_unknown` after its 2-minute lease, and is not resent without lecturer confirmation. If the slow send does complete, it is still recorded as `sent`. |

### 6.4 Missing Addresses

A missing address never blocks saving the mark. The email record is created as `failed` with `missing_recipient`, so the lecturer can see which students were not emailed. After the address is added, the retry action picks up the new address.

### 6.5 Recipient Isolation

Every email is sent to exactly one recipient, with no CC or BCC, and contains only that student's result. The recipient is the email address of the student linked to the result's enrollment.

---

## 7. API

All endpoints require an authenticated lecturer and only return records for the lecturer's own courses. Records belonging to another lecturer return `404 Not Found`.

### 7.1 Result Email Object

```json
{
  "id": 1,
  "result": 1,
  "result_version": 1,
  "is_current": true,
  "student_number": "12345678",
  "recipient": "12345678@mynwu.ac.za",
  "subject": "PostGrade result: Test 1",
  "body": "Hi Alice,\n\nYour result for Test 1 is:\n\n75.00 / 100.00\n75.00%\n\nRegards,\nPostGrade",
  "status": "sent",
  "failure_reason": "",
  "attempts": 1,
  "max_attempts": 3,
  "run_after": "2026-09-24T20:30:27.993821Z",
  "approved_at": null,
  "sent_at": "2026-09-24T20:30:28.022168Z",
  "created_at": "2026-09-24T20:30:27.993821Z",
  "updated_at": "2026-09-24T20:30:28.022168Z"
}
```

| Field | Description |
|---|---|
| `result_version` | The result version this email was written for. |
| `is_current` | `false` if the mark has changed since; such an email will not be sent. |
| `recipient`, `subject`, `body` | Exactly what is (or was) sent. Serves as the preview. |
| `failure_reason` | A code from Section 5. The full mail server error is kept for administrators only and is not returned. |

### 7.2 Mark Submission (changed)

`POST /api/submissions/{id}/mark/`

The response is unchanged, with one added field, `email_delivery`, containing the result email object. The mark is saved even if the email later fails.

```json
{
  "id": 1,
  "assessment": 1,
  "enrollment": 1,
  "student_number": "12345678",
  "student_name": "Alice Smith",
  "mark": "75.00",
  "percentage": 75.0,
  "created_at": "2026-09-24T20:30:27.981974Z",
  "updated_at": "2026-09-24T20:30:27.981974Z",
  "email_delivery": {
    "id": 1,
    "status": "queued",
    "...": "see 7.1"
  }
}
```

### 7.3 Endpoints

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| `GET` | `/api/assessments/{assessment_id}/result-emails/` | List an assessment's result emails, newest first (preview and status tracking). | `200` |
| `GET` | `/api/result-emails/{id}/` | One result email. | `200` |
| `POST` | `/api/result-emails/{id}/approve/` | Approve one email (`awaiting_approval` → `queued`). | `202` with the email |
| `POST` | `/api/assessments/{assessment_id}/result-emails/approve/` | Approve all current emails awaiting approval for an assessment. | `202` with `{"approved": <count>}` |
| `POST` | `/api/result-emails/{id}/retry/` | Retry a `failed` email. | `202` with the email |

### 7.4 Retry

`POST /api/result-emails/{id}/retry/`

**Inputs**

```json
{ "confirm_duplicate": true }
```

`confirm_duplicate` is required only for `delivery_unknown` emails.

**Processing**

1. The email must be `failed` and for the current mark.
2. A `delivery_unknown` email requires `confirm_duplicate: true`.
3. The recipient is refreshed from the student's current email address.
4. The email is queued with a fresh set of attempts.

---

## 8. Error Responses

Errors use the standard format described in `DOCS/RECOGNITION_EVIDENCE_API.md`, Section 7.1.

| Status | Condition | Body |
|---|---|---|
| `400` | Approve an email that is not awaiting approval | `{"detail": "Only emails awaiting approval can be approved."}` |
| `400` | Approve or retry an email for an outdated mark | `{"detail": "This email is for an outdated mark."}` |
| `400` | Retry an email that is not failed | `{"detail": "Only failed emails can be retried."}` |
| `400` | Retry `delivery_unknown` without confirmation | `{"detail": "This email may already have been delivered. Retry with confirm_duplicate to send it again."}` |
| `400` | Retry while the student still has no address | `{"detail": "The student has no email address."}` |
| `401` | Missing or invalid token | `{"detail": "Authentication credentials were not provided."}` |
| `404` | Email or assessment not found, or belongs to another lecturer | `{"detail": "No ResultEmail matches the given query."}` |

---

## 9. Configuration

| Setting | Value | Location |
|---|---|---|
| Release policy | `automatic` | `RESULT_EMAIL_RELEASE_POLICY` in `.env` / `config/settings.py` |
| SMTP timeout | 30 s | `EMAIL_TIMEOUT`, `config/settings.py` |
| Maximum attempts | 3 | `ResultEmail.max_attempts` default, `distribution/models.py` |
| Retry delays | 1 min, 4 min | `RETRY_DELAYS`, `distribution/dispatch.py` |
| Send lease | 2 min | `LEASE_DURATION`, `distribution/dispatch.py` |
| Lease recovery interval | 60 s | `RECOVERY_INTERVAL`, `distribution/management/commands/run_mail_worker.py` |

`EMAIL_TIMEOUT` must stay well below the send lease, otherwise a slow but successful send would be recorded as `delivery_unknown`.

---

## 10. Compatibility

- `POST /api/submissions/{id}/mark/` returns the same fields as before, plus `email_delivery`. The existing Vue frontend is unaffected.
- **Behaviour change:** the email is sent by the mail worker, not during the request. A mail worker must be running for emails to be sent.
- `POST /api/students/{id}/email/` (manual email to a student) is unchanged and still sends immediately.
- Database changes: `assessments/0003_result_version` adds `Result.version` (existing results start at 1) and `distribution/0001_initial` adds the outbox table. No existing data is modified.

---

## 11. Issues List

| ID | Description | Status |
|---|---|---|
| 01 | The Vue frontend has no screen to review, approve or retry result emails. Until it does, the `approval` policy cannot be used in practice. | TBD |
| 02 | Recipients use the student's stored email address. The Functional Specification derives addresses as `studentnumber@mynwu.ac.za`; a class-list import rule could populate this. | TBD |
| 03 | Emails contain the mark only. Attaching the marked script (Functional Specification 10.2) is not implemented. | TBD |
| 04 | Retry limit and delays are fixed in code (Technical Specification Issue 05). | TBD |
| 05 | Mail provider delivery reports (bounces after acceptance, "Delivered" state in Functional Specification 10.4) are not tracked; `sent` means accepted by the mail server. | TBD |
| 06 | A downloadable delivery report (Functional Specification 10.6) is not implemented; the list endpoint provides the underlying data. | TBD |
| 07 | Concurrent edits to the same result through `PATCH /api/results/{id}/` are not serialised, and could assign the same version twice. The mark endpoint locks the result and is not affected. | TBD |
