# Database integrity, performance and recovery review (#10)

This review covers the script-only system. Result creation, gradebook queries, max_mark and weight rules from the original ticket are obsolete: PR #44 removed that functionality and migrated historical marked scripts to verified or needs_verification. Numeric grading is not restored here.

## Membership and workflow rules

Normal Enrollment saves lock the course/student, validate a shared owner and reject reassignment of referenced memberships. Normal Submission saves validate the assessment course/owner against the enrollment. Normal course/student owner transfers are blocked while memberships exist. API serializers already reject other owners; these model guards also cover ordinary ORM saves. Workflow services retain their transactional scope/version checks. The worker locks submission before the proposed enrollment: a suggestion deleted or moved to an invalid class/owner becomes needs_verification, rather than attempting a dangling FK write. Current job/attempt fencing still prevents cancelled or stale workers from changing the submission.

New audit entries snapshot enrollment ID, student ID, student number and course ID. They survive contact edits and nullable enrollment links after deletion, while the submission/audit row survives. Ordinary audit saves cannot rewrite those snapshots; admin remains read-only. Migration 0014 backfills available current references in batches of 500. origin=transition identifies new captures; origin=migration_current_reference identifies backfills. A backfill cannot reconstruct the original number if it changed before this release, or recover links already deleted; missing identities remain empty dictionaries.

Run `python manage.py audit_database_integrity --fail-on-invalid` before release. It reports invalid enrollment owners and submission scopes, verified scripts without enrollment, duplicate script groups and unsent orphan mail. Only invalid owner/scope counts make the strict command fail; orphan/duplicate counts are review items, not silently repaired. The command is read-only and contains no student names or numbers in output.

`bulk_create`, QuerySet.update and raw SQL bypass model methods. Migration `submissions.0015_database_membership_constraints` now uses derived database keys and composite foreign keys to enforce enrollment owners and submission course membership even for those writes. It blocks migration on existing mismatches without silently repairing them. See [DATABASE_MEMBERSHIP_CONSTRAINTS.md](DATABASE_MEMBERSHIP_CONSTRAINTS.md) for locking, explicit repair, rollback and PostgreSQL concurrency tests. Model clean/save still does not enforce unrelated workflow/audit rules for arbitrary SQL.

## Foreign-key deletion and duplicate policy

| Operation | Existing behavior retained |
| --- | --- |
| Course/assessment DELETE API | Archive; retain scripts, files, enrollments, audits and email history, cancel active recognition and supersede unsent mail. |
| Course/assessment hard ORM deletion | Existing cascades remain; normal API has no hard-delete route. |
| Account hard deletion | Cascades owned courses/contacts and associated domain records; not a restore or retention workflow. |
| Global student deletion | Cascades all memberships; clears nullable submission/audit/email enrollment links. Audit snapshots retain captured identity if their submission survives. |
| Enrollment deletion | Clears nullable links; recognition/verification rechecks reject a missing identity, and delivery eligibility rejects missing verified membership. No class-withdrawal API exists. |
| Submission deletion | Cascades audits, recognition attempts and jobs; preserves email snapshots with a null submission and supersedes unsent mail. Original/crop cleanup runs after commit. |
| Email record deletion | Removes its private attachment snapshot after commit. |

Multiple submissions per assessment/enrollment are currently allowed. File replacement is explicit/versioned, and mail requests are unique per submission/version; that does not deduplicate two separately uploaded scripts. No new uniqueness or deletion restriction is invented. [#50](https://github.com/Devon-du-Toit/PostGradeDjango/issues/50) requires approval of withdrawal, PROTECT/soft deletion, audit/media/email retention, account deletion and duplicate/replacement policy before changing these semantics. An SMTP send already in progress cannot be recalled.

## Query measurements

Fixture: 300 students, two courses (one archived), two assessments, 330 enrollments, 631 scripts, 1260 recognition attempts, 630 jobs and 630 audits. The legacy fixture deliberately includes two scripts per active enrollment and covers OCR/bubble choices, old marked records, an orphan marked record, recognition states, archives and sent/queued historical email. It is representative of these schema cases, not production cardinality or distribution.

| Endpoint | Page 1 | Page 25 | Page 100 | Real JWT at page 25 |
| --- | ---: | ---: | ---: | ---: |
| /api/submissions/ | 4 | 4 | 4 | 5 |
| /api/submissions/verification-queue/ | 4 | 4 | 4 | 5 |

The forced-auth counts include pagination count, submission select and recognition-attempt/job prefetches; real JWT adds its user lookup. Filter validation can add fixed queries. Existing FK/indexes and prefetches avoid N+1 growth. The captured queue EXPLAIN ANALYZE is in the evidence JSON; its small local execution time does not establish a production SLA. No speculative indexes were added. Gradebook is retired (404), so there is no live gradebook query to optimize. Retry-heavy evidence memory use and production selectivity remain measurement targets in [#52](https://github.com/Devon-du-Toit/PostGradeDjango/issues/52); bulk CSV optimization remains #42.

## Migration and recovery evidence

On 2026-10-06, isolated PostgreSQL 17 databases on port 55424 demonstrated:

1. Fresh migration of every installed app with no pending migrations and a clean Django check.
2. Upgrade from the pre-retirement schema with 300 students, 631 scripts, 300 Result rows and historical mail; active numeric results are retired, old sent text is retained as history, queued legacy mail is superseded, marked/orphan states are converted and audit snapshots backfilled with provenance. Leading-zero student numbers and file references survive.
3. Current private script-email snapshot creation without running a mail worker or sending email.
4. Custom-format pg_dump, pg_restore into a separate empty database and media copying into a separate directory.
5. Exact row counts and SHA-256 digests for ten domain tables, all three media file hashes, clean migration state and Django check. Protected original download and private email preview were verified on the restored data.

The fixture uses one shared synthetic source PDF, one crop and one independent delivery snapshot; it does not measure production storage volume. No live database or real student data was accessed. [Evidence JSON](evidence/database-review-2026-10-06.json) includes counts, digests, query counts and the SQL plan. [tools/database_review.py](../tools/database_review.py) reproduces the legacy fixture, measurements and manifests; it refuses non-review database/media names, requires DEBUG and refuses legacy seeding unless the database is empty. Binary dumps and synthetic media remain local, outside Git.

See [BACKUP_RESTORE.md](BACKUP_RESTORE.md) for the complete database-plus-media procedure. [#52](https://github.com/Devon-du-Toit/PostGradeDjango/issues/52) covers an approved anonymized staging snapshot, production-scale plans, recovery objectives, scheduled backups and restore drills under deployment #14. This exercise does not replace validation against that dataset.

## Release

Apply migration 0014 after backing up database and media; run the integrity audit. Existing audit identities use available references and are explicitly marked as backfills. No Vue contract or grading endpoint changes are required. Do not roll back destructive historical grading migrations to attempt data recovery; restore a matching database/media backup with the matching code revision.
