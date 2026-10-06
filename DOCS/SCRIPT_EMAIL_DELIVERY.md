# Verified script email delivery

The workflow is upload → recognise → verify → explicitly request script delivery.
PostGrade does not collect numeric marks, assessment maxima or weights, calculate grades, or maintain results/gradebooks.

## Request and release

`POST /api/submissions/{id}/email/` requires an authenticated owner and a verified submission with a class enrollment. No mark or email body is supplied. It returns `202` with the delivery record. Invalid/unverified scripts return `400`; unavailable, archived or other-owner scripts return `404`.

The same submission/version reuses the existing delivery record, including one already sent. Concurrent requests serialize on the submission and create one record. To retry a failure, use the retry action rather than making a second request.

`SCRIPT_EMAIL_RELEASE_POLICY=automatic` queues an explicit request immediately. `approval` creates an awaiting-approval record. Neither policy emails a script merely because it was uploaded or verified. A missing recipient produces a failed record; fixing the address and retrying still requires approval if it was never approved.

## Message and attachment

The outbox snapshots the recipient, subject, body, verified enrollment, submission version, original attachment filename and a private copy of the original file. It sends one student one script, retaining PDF/JPEG/PNG content. The body says the verified script is attached; no score or percentage appears.

The web process and mail worker must share private media storage, including `script-emails/`. No public attachment URL is exposed. The preview API returns the attachment filename, not file bytes. A missing/empty snapshot fails with `attachment_unavailable`; it never sends a body-only message. Each snapshot adds up to the configured upload limit to storage.

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/submissions/{id}/email/` | Request/reuse delivery for the verified file |
| GET | `/api/assessments/{id}/script-emails/` | Paginated delivery records; `status` and `search` filters |
| GET | `/api/script-emails/{id}/` | Stored message, attachment name and delivery state |
| POST | `/api/script-emails/{id}/approve/` | Approve one current awaiting record |
| POST | `/api/assessments/{id}/script-emails/approve/` | Approve current awaiting records |
| POST | `/api/script-emails/{id}/retry/` | Retry a failed current record |

Records expose `submission`, `submission_version`, `student_number`, `attachment_filename`, `is_current`, recipient/message fields, timestamps, attempts and a safe failure reason. Internal provider errors and storage names are withheld.

## States and retries

States: `awaiting_approval`, `queued`, `sending`, `sent`, `failed`, `superseded`.
Run `python manage.py run_mail_worker` alongside the web and recognition processes.
The worker claims database rows with a lease and attempt fencing. Provider errors retry after one and four minutes, up to three attempts. A refused recipient or missing attachment needs intervention. A backend send return value of zero is a failure, never a sent record.

An expired send becomes `failed / delivery_unknown`. It may already have reached the student. A retry requires JSON `{"confirm_duplicate": true}`; strings such as `"false"` do not authorize a duplicate. Sent or outdated records cannot be retried. The stable Message-ID aids mail-client duplicate recognition but SMTP is not an exactly-once protocol.

## Changes, deletion and archiving

Repeating the same verification is idempotent. Correcting the verified enrollment increments the submission version and supersedes unsent deliveries. Replacing a file requires its current version, clears verification, cancels recognition, supersedes unsent deliveries and queues recognition for the replacement. Its old delivery retains the immutable old attachment. Generic edits cannot move a script to another assessment or change its student; use verification.

The mail worker checks the current verified version/enrollment and active parents before delivery. Archiving cancels recognition and supersedes unsent mail, retaining files and sent history. Deleting a submission leaves email history with a null submission; it cannot be sent, approved or retried. Deleting a delivery record removes its snapshot after transaction commit. An SMTP send already in progress cannot be recalled.

## Migration and deployment

Deploy with the matching Vue branch; the old mark/result/gradebook/statistics/result-email endpoints are removed, not compatibility aliases. Follow [MARKS_REMOVAL.md](MARKS_REMOVAL.md). Historical result-email messages remain admin history; they are not converted into script deliveries or exposed through active script endpoints. No existing script is automatically emailed by the migration.

Tests: `python manage.py test distribution submissions.tests.test_verification submissions.tests.test_submission_lifecycle assessments.tests.test_lifecycle`.
