# Database integrity review

The active domain no longer stores assessment scores or Result rows. The grading-removal migration drops their table/columns; back up historical numeric data before applying it. See [MARKS_REMOVAL.md](MARKS_REMOVAL.md).

## Enforced workflow rules

- Course, Student and Enrollment uniqueness constraints remain.
- Valid submission statuses exclude marked. Existing marked scripts are migrated to verified or needs_verification.
- Verification locks the submission, checks course membership and writes actor/state/enrollment audit data. Repeating an unchanged verification is idempotent.
- Replacement requires a matching version under the row lock, invalidates enrollment/recognition, increments version and supersedes unsent delivery.
- Script email idempotency keys uniquely identify a submission/version; scheduling serializes concurrent requests. Attachments are stored snapshots. The worker checks active scope, current verified version and enrollment.
- Archiving cancels queued/running recognition and supersedes unsent mail while retaining evidence and history.

## Remaining lifecycle work

Direct ORM writes do not automatically run full_clean. Owner/course membership must still be respected outside the API. User/contact/enrollment deletion cascade choices, long-term audit retention, enrollment withdrawal, archive restore/key reuse and duplicate-script policy remain separate decisions. Submission deletion nulls email history's subject link; that history is not deliverable.

Storage is not transactional with PostgreSQL. Snapshot creation cleans up on local scheduling failure; database/media backup consistency and orphan-storage reconciliation remain operational concerns. In-progress SMTP delivery cannot be recalled. Use the backup/restore runbook and a representative staging test.


Issue #9 records the current [class-list and assessment lifecycle decisions](CSV_IMPORT_AND_LIFECYCLE.md). Follow up here on enrollment withdrawal, restricting global contact deletion when verified scripts exist, immutable audit identity after deletion and recognition fencing against deleted enrollment records. Bulk import query optimization remains issue #42.
