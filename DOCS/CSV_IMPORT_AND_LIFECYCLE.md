# Class-list CSV import and lifecycle decisions (#9)

This release extends the existing import and archive workflow. It does not restore numeric grading, assessment weights, maximum marks, Result records or gradebooks removed by PR #44.

## Import contract

POST /api/courses/{id}/import-students/ accepts a multipart file, dry_run and update_existing. Both options default to false and accept normal boolean forms (including multipart true/false); invalid options return 400 before any import writes. The course must be owned and active.

Files must be UTF-8, with or without a BOM. Maximum file size is 2 MiB; reads are capped at the limit plus one byte, even if the uploaded size is incorrect. Maximum data records is 5000, including blank records. CSV parsing uses strict quoting; broken quoting or parser field-size errors return row-specific 400 errors, rather than 500. Parsing stops after an unrecoverable syntax error.

Required headers are student_number, first_name, last_name, email. Header/value whitespace is trimmed; headers remain case-sensitive. Duplicate or blank header names and missing required columns are file errors. Additional named columns are accepted and ignored, but every nonblank record must match the full header width. Empty physical lines, whitespace-only lines and correctly shaped wholly blank rows are skipped. Extra values never hide a malformed blank record.

Every nonblank row is validated, including incoming details for an existing student when updates are disabled. Student numbers remain strings without numeric conversion, preserving leading zeros. Duplicate trimmed student numbers are errors. An invalid row prevents the entire file from being written. Row identifiers refer to the physical starting line of a CSV record, including preceding blank lines and multiline quoted fields.

## Preview and existing-student policy

- dry_run=true returns the proposed summary and mismatches without creating/updating students or enrollments.
- Existing students are matched by owner plus exact student_number. Other owners can use the same number and are never read or changed by the import.
- update_existing=false reuses the existing contact and reports differences in first_name/last_name/email. It does not silently apply incoming details.
- update_existing=true explicitly applies valid incoming contact fields. Student identity/ownership is not reassigned. Invalid incoming fields still fail the whole import.
- Imports add class memberships; they do not remove students omitted from the file. Repeat imports are idempotent for students/enrollments.
- The existing summary keys total, failed, rows_processed, created, updated, matched_unchanged and enrolled remain compatible with Vue. enrolled counts processed target memberships, including ones already present; it is not a count of newly inserted enrollment rows.

A preview is informational, not a database reservation or confirmation token. A subsequent import request validates its file against the then-current database. Within each request, application locks the active course and affected owned students in ID order, then verifies the planned identities/contact fields before writing. A changed/deleted/newly appeared student returns 409 with instructions to preview again. Database conflicts also return a safe 409 after rollback. All contact updates, new students and memberships commit together or none do. A plan with validation errors or another owner cannot be applied directly.

Ordinary contact updates now save a fresh locked row, so a partial edit cannot restore unrelated fields from an old serializer instance after a CSV update. Concurrent duplicate student saves return validation errors instead of raw database failures. Large-file bulk lookup/bulk_create performance remains the separate [#42](https://github.com/Devon-du-Toit/PostGradeDjango/issues/42) follow-up.

## Course and assessment decisions

| Action | Current policy |
| --- | --- |
| Delete course or assessment through API | Archive only; retain contacts, enrollments, scripts, files, evidence, audits and delivery history. No restore or hard-delete endpoint is introduced. |
| Writes after archive | Reject creation of assessments/enrollments and edits of courses/assessments, even if validation happened while active. Lock/recheck the course before child rows. Existing upload/import/delivery active-scope checks remain. |
| Archive queued work | Cancel active recognition jobs and supersede unsent email records. Sent history/attachments remain. SMTP already in progress cannot be recalled. |
| Edit assessment name/date | Allowed while active, including after scripts are verified. Verification identifies the enrollment/file, not a score. Existing email subject/body/attachment snapshots retain the previously requested content. |
| Change weights/maximum marks/results | Unavailable: fields/models/endpoints were removed. Numeric scoring inputs are rejected. |
| Remove a class enrollment | No withdrawal/removal API currently exists; imports are additive. Do not treat deleting a global student contact as class-only withdrawal. |
| Delete global student contact | Existing physical deletion remains: all its enrollments cascade, submission/audit enrollment links become null, and script-mail snapshots retain their text/attachment with null enrollment. Current eligibility checks prevent delivery without a verified enrollment. |

The [database lifecycle review](DB_REVIEW.md) fixes audit snapshots and deleted recognition suggestions. The remaining product decisions are tracked in [#50](https://github.com/Devon-du-Toit/PostGradeDjango/issues/50): define class withdrawal without global contact deletion, decide hard-delete restrictions when verified scripts/history exist, set the retention period for immutable audit identities and decide withdrawal/cancellation behavior for in-flight work. Archive restore/key reuse and hard account deletion also need that retention decision. This release preserves the existing deletion behavior rather than inventing a withdrawal or retention policy.

See [ARCHIVING.md](ARCHIVING.md), [DB_REVIEW.md](DB_REVIEW.md), [MARKS_REMOVAL.md](MARKS_REMOVAL.md) and [SCRIPT_EMAIL_DELIVERY.md](SCRIPT_EMAIL_DELIVERY.md).

## Verification

CSV regressions cover BOM/encoding, input caps, quoted/multiline records, physical lines, header width, blanks, duplicate identities, invalid flags, dry runs, explicit updates, leading zeros, repeat imports, owner isolation, stale/deleted/new identities and transaction rollback. Concurrent prebuilt plans can consume an absent identity only once; the other returns 409. Lifecycle regressions validate serializers before archive and confirm their later save is rejected, as well as enrollment races and retired grading inputs.

There is no data migration or frontend payload change. Clients should preview again after 409. Existing archive and delivery regressions remain part of the backend suite.


## Bulk query budget

CSV validation loads the owner-scoped student records for the whole bounded file in one query, while reusing the normal serializer's field rules. File duplicates and stale-preview checks remain separate; ordinary student API edits retain their per-request uniqueness check.

Application locks the active course first and existing students in primary-key order, rechecks every snapshot, then uses batches of at most 500 for student creation, explicit contact updates and missing enrollment creation. No conflicting row is ignored. A constraint error rolls back all batches and returns 409. Bulk updates explicitly advance updated_at; owner keys and student numbers are never changed by contact updates. These bulk writes stay within the validated, locked service; they are not a substitute for database membership constraints.

PostgreSQL service-level regression budgets for a 300-student class (including transaction savepoint/release in tests): validation 1 query; new students/enrollments 7; repeat unchanged import 5; contact updates 6. Request authentication and initial course lookup add their own queries. A 1001-row test verifies complete multi-batch writes. Parsing limits, physical row errors, dry-run summaries, opt-in contact updates and additive enrollment semantics are unchanged.
