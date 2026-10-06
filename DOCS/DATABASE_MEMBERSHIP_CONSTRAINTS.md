# PostgreSQL membership enforcement (#51)

Migration `submissions.0015_database_membership_constraints` enforces two invariants for normal saves, `bulk_create`, `QuerySet.update` and ordinary SQL:

- An enrollment's student and course have the same owner.
- A submission's enrollment, when present, belongs to its assessment's course.
- An enrollment's student identity cannot change while a submission still references it, including a same-owner replacement student.

The database owns three redundant, non-ORM columns: `students_enrollment.db_owner_key`, `submissions_submission.db_course_key` and `submissions_submission.db_student_key`. BEFORE INSERT/UPDATE triggers derive them from the course, assessment and enrollment respectively, overriding attempted writes. Composite unique keys on parent tables support composite foreign keys. Parent owner/course/student reassignment is consequently rejected while it would invalidate an existing relationship. A shape CHECK requires the student key exactly when an enrollment is linked, preventing nullable composite-FK bypass. Null enrollment links remain valid; Django deletion still sets these links to null, including audit references. Existing authorization, archive, verification and audit services remain responsible for their own rules: these constraints do not grant delegated access or replace workflow auditing.

## Why foreign keys

A trigger that only queries another row can admit a race under PostgreSQL's normal READ COMMITTED isolation. PostgreSQL foreign keys acquire referential-integrity row locks and recheck concurrent changes. Either a competing parent update or child insert must fail; both cannot commit an incompatible pair. The derivation triggers do not decide validity from their SELECT results alone. No Python model validation or application lock is needed for this enforcement.

Constraints are `DEFERRABLE INITIALLY IMMEDIATE`. Ordinary writes fail at the statement that violates the invariant. A deliberately coordinated repair may defer named constraints within one transaction; they must validate before commit. Superuser/replication-role operations that disable triggers are outside this protection and must remain restricted to database administrators. Applications must not use `session_replication_role=replica` for imports or restores.

## Before migration

1. Freeze writes and stop workers; capture the paired database/media backup using [BACKUP_RESTORE.md](BACKUP_RESTORE.md).
2. Run `python manage.py audit_database_integrity --fail-on-invalid` and inspect the counts. Record approved row-level repairs privately, including actor and reason; never publish student data in GitHub evidence.
3. If mismatches exist, stop. Do not silently change owner, move a script, clear identity, or discard rows. Agree the correct membership with the lecturer. Use an explicit, audited repair transaction on the prior schema and rerun the audit.
4. Run `python manage.py migrate --noinput`. The migration acquires exclusive locks on the five related tables before its preflight, backfill and constraint installation. Existing invalid data raises a specific exception and rolls the atomic migration back. It never repairs incompatible records. The added keys are deterministic copies of already-valid relationships.
5. Rerun the integrity audit, deployment checks and protected workflow smoke tests, then resume workers/writes.

The migration scans and backfills existing rows and builds five composite unique indexes. Schedule a maintenance window; staging timing and recovery acceptance remain deferred with #52. Do not claim zero downtime. This migration is PostgreSQL-specific, matching the supported application database.

## Repairs and rollback

Constraints may be deferred only for a reviewed transaction that finishes with every invariant valid. `SET CONSTRAINTS ALL IMMEDIATE` forces validation before the operator commits; an error must roll back the transaction. Use services for lecturer identity corrections so audit snapshots and email supersession remain correct. A database administrator must record any exceptional bulk/SQL repair separately because SQL does not create application audit entries.

Reverse the migration only with writes/workers frozen and a paired backup. Its reverse SQL removes five foreign keys, two derivation triggers/functions, the hidden columns (and shape CHECK) and five redundant unique constraints. It leaves all business records and the original Django foreign keys unchanged. Rolling back reopens the bulk/SQL bypass; it is not a repair strategy for inconsistent data.

## Validation

`submissions.tests.test_database_membership` uses real PostgreSQL statements and transactions. It covers incompatible bulk inserts, parent/child queryset reassignments (including same-owner student identity replacement), hidden-key spoof attempts, nullable enrollment/deletion, both enrollment/owner race orderings, concurrent student-owner reassignment, concurrent assessment/enrollment movement versus script insertion, concurrent student identity switching, migration reversal and fail-closed preflight. The concurrent cases have bounded statement/lock timeouts and require a foreign-key rejection rather than accepting either a deadlock or a successful invalid write.

The read-only audit regression deliberately defers one named constraint within its test transaction, detects intermediate bad data, removes that synthetic record and restores immediate checking. No invalid row commits.
