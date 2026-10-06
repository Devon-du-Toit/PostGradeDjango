# Submission transitions and corrections

Issue #6 is implemented against the script-only workflow. PR #44 removed marks and Result records, migrating historical marked submissions to verified (or needs_verification when no enrollment exists). This change adds no grading states and needs no data migration.

## Transition rules

| Current state | Allowed next states |
| --- | --- |
| uploaded | processing, matched, needs_verification |
| processing | processing (file replacement), matched, needs_verification, recognition_failed, verified |
| matched | verified, needs_verification, processing |
| needs_verification | verified, processing |
| recognition_failed | verified, processing |
| verified | verified (explicit correction), processing (file replacement) |

Upload creates a processing submission and a creation audit with null previous state. Recognition completion/failure, manual verification/correction, retry and replacement all use record_status_change. Each accepted change increments version and creates an audit with actor (null for workers), timestamp, previous/new enrollment and status, and reason, in the same transaction. Repeated confirmation of the same verified enrollment and repeated retry while processing are no-ops. Status validation remains a database check constraint; legal transitions depend on the locked previous row and are enforced by the transition service, rather than a check constraint that cannot inspect the old row.

## API requests

- POST /api/submissions/{id}/verify/: {"enrollment": 42, "version": 3}. Rejects a stale version and cannot silently change a verified student. Legacy clients may omit version for initial verification or repeat confirmation; they still cannot reassign a verified identity. The matching Vue change sends the version of the reviewed script, protecting against replacement or recognition completing during review.
- POST /api/submissions/{id}/correct/: {"enrollment": 43, "version": 4, "reason": "Wrong student selected"}. Requires a verified script, current version, and nonblank reason. Same-course and owner checks apply. A stale competing correction is rejected, including a repeat with its consumed version. Unsent email records are superseded; a new explicit delivery request uses the corrected identity/version. Same-identity corrections make no change.
- POST /api/submissions/{id}/retry-recognition/: {"version": 3}. Version is accepted and checked under lock; omitted versions remain compatible with legacy clients. Accepted retries clear prior suggestions, increment version and record the requesting lecturer.
- PATCH /api/submissions/{id}/: multipart file and version. Replacement clears identity, records the previous identity, cancels existing jobs and queues recognition. Changing assessment/student through generic updates is rejected.

## Concurrency and history

Web mutations lock active course, assessment, then submission. Replacement locks active jobs before the submission, matching workers' job-before-submission order. Workers lock only their submission row, without implicitly locking joined parents. Worker attempts must still own the running job; cancelled/stale attempts and results arriving after manual verification cannot alter the submission. Audit failures roll back the associated status/version change. Audit history remains available in Django admin; archived records remain hidden from active owner APIs.

Existing records and status names remain unchanged. Old records do not acquire fabricated historical audits. Clients should reload after a stale-write error and review the new file/recognition evidence before resubmitting.
