# PostgreSQL membership enforcement (#51)

Migration `submissions.0017_database_membership_constraints` follows the QR and withdrawal/history migrations and enforces these invariants for normal saves, `bulk_create`, `QuerySet.update` and ordinary SQL:

- An enrollment's student and course have the same owner.
- A submission's enrollment, when present, belongs to its assessment's course.
- An enrollment's student identity cannot change while a submission still references it, including a same-owner replacement student.
- A QR page's submission and retained source upload belong to the same assessment; suggested and linked memberships belong to that assessment's course.
- A linked QR page has the same enrollment as its parent script when the transaction commits.

The database owns five redundant, non-ORM columns: `students_enrollment.db_owner_key`, `submissions_submission.db_course_key`, `submissions_submission.db_student_key`, `submissions_scriptpage.db_assessment_key` and `submissions_scriptpage.db_course_key`. BEFORE INSERT/UPDATE triggers derive them from the course, assessment, enrollment and parent script, overriding attempted writes. Composite unique keys on parent tables support composite foreign keys. Parent owner/course/student/source reassignment is consequently rejected while it would invalidate an existing relationship. A shape CHECK requires the student key exactly when an enrollment is linked, preventing nullable composite-FK bypass. Null optional enrollment links remain valid; clearing links derives the corresponding null student key. The retention policy protects referenced memberships from ordinary deletion; genuinely unreferenced memberships can still be deleted. Existing authorization, archive, verification and audit services remain responsible for their own rules: these constraints do not grant delegated access or replace workflow auditing.

Student reassignment is fenced once an enrollment is linked to a submission. A suggestion-only enrollment is constrained to the correct owner/course; this migration does not make its student identity immutable when no submission links it. Ordinary APIs do not expose enrollment reassignment. Exceptional SQL maintenance must still review recognition suggestions and record any identity changes explicitly.

## Why foreign keys

A trigger that only queries another row can admit a race under PostgreSQL's normal READ COMMITTED isolation. PostgreSQL foreign keys acquire referential-integrity row locks and recheck concurrent changes. Either a competing parent update or child insert must fail; both cannot commit an incompatible pair. The derivation triggers do not decide validity from their SELECT results alone. No Python model validation or application lock is needed for this enforcement.

Ten foreign keys are `DEFERRABLE INITIALLY IMMEDIATE`. Ordinary scope writes fail at the statement that violates the invariant. The QR parent/page identity foreign key is `DEFERRABLE INITIALLY DEFERRED`: verification, late intake and corrections change the parent enrollment and clear/relink pages within one transaction, so intermediate differences are allowed but cannot commit. Tests exercise both parent-first and page-first updates. A deliberately coordinated repair may defer named constraints within one transaction; they must validate before commit. Superuser/replication-role operations that disable triggers are outside this protection and must remain restricted to database administrators. Applications must not use `session_replication_role=replica` for imports or restores.

## Before migration

1. Freeze writes and stop workers; capture the paired database/media backup using [BACKUP_RESTORE.md](BACKUP_RESTORE.md).
2. Run `python manage.py audit_database_integrity --fail-on-invalid` and inspect the counts. Record approved row-level repairs privately, including actor and reason; never publish student data in GitHub evidence.
3. If mismatches exist, stop. Do not silently change owner, move a script, clear identity, or discard rows. Agree the correct membership with the lecturer. Use an explicit, audited repair transaction on the prior schema and rerun the audit.
4. Run `python manage.py migrate --noinput`. The migration acquires exclusive locks on the seven related tables before its preflight, backfill and constraint installation. Existing invalid data, including QR source/suggestion/link mismatches, raises a specific exception and rolls the atomic migration back. It never repairs incompatible records. The added keys are deterministic copies of already-valid relationships.
5. Rerun the integrity audit, deployment checks and protected workflow smoke tests, then resume workers/writes.

The migration scans and backfills existing rows and builds nine composite unique indexes supporting eleven foreign keys. Schedule a maintenance window; staging timing and recovery acceptance remain deferred with #52. Do not claim zero downtime. This migration is PostgreSQL-specific, matching the supported application database. The audit reports aggregate `invalid_qr_page_scopes`, `invalid_qr_page_enrollments` and `invalid_qr_page_links`; before the QR page table exists it explicitly returns `qr_schema_available=false` and null QR counts, rather than pretending it checked absent tables.

## Repairs and rollback

Constraints may be deferred only for a reviewed transaction that finishes with every invariant valid. `SET CONSTRAINTS ALL IMMEDIATE` forces validation before the operator commits; an error must roll back the transaction. Use services for lecturer identity corrections so audit snapshots and email supersession remain correct. A database administrator must record any exceptional bulk/SQL repair separately because SQL does not create application audit entries.

Reverse to the preceding `submissions.0016_submissionfilerevision_and_more` only with writes/workers frozen and a paired backup. Reverse SQL removes eleven foreign keys, three derivation triggers/functions, the hidden columns (and shape CHECK) and nine redundant unique constraints. It leaves all business records, original Django foreign keys and history policy unchanged. Rolling back reopens the bulk/SQL bypass; it is not a repair strategy for inconsistent data.

## Validation

`submissions.tests.test_database_membership` uses real PostgreSQL statements and transactions. It covers incompatible bulk inserts, parent/child queryset reassignments (including same-owner student identity replacement), hidden-key spoof attempts, nullable enrollment/deletion, both enrollment/owner race orderings, concurrent student-owner reassignment, concurrent assessment/enrollment movement versus script insertion, concurrent student identity switching, migration reversal and fail-closed preflight. The concurrent cases have bounded statement/lock timeouts and require a foreign-key rejection rather than accepting either a deadlock or a successful invalid write.

A workflow lock-order regression holds a running job while a competing assessment/course archive owns its parent row and waits on that job. Worker completion and archive must both finish under bounded timeouts with the script hidden by its archived parent; it exercises the new foreign keys alongside existing application lock ordering.

The read-only audit regression deliberately defers one named constraint within its test transaction, detects intermediate bad data, removes that synthetic record and restores immediate checking. No invalid row commits.

`submissions.tests.test_qr_database_membership` covers cross-assessment/source and enrollment violations through bulk/queryset/raw SQL, parent reassignment, hidden-key spoof attempts, both linked-identity update orderings, bad-commit rejection, populated QR preflight and read-only audit failures, pre-QR schema reporting and concurrent parent/source moves against page insertion.
