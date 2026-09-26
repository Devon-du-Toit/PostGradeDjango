# Database Integrity Review (#10)

## Findings

### Not enforced at DB level

1. Result.course match. Result.clean() checks enrollment belongs to the same course as assessment. Not enforced on save, only on full_clean(). DB can store mismatched rows.

2. Enrollment.owner match. Enrollment.clean() checks student and course have the same owner. Not enforced on save.

3. Result.mark <= Assessment.max_mark. Checked in Result.clean(). Not enforced on save.

### Concurrency

Result creation has no transaction or locking around create-or-update. Two simultaneous requests can cause an unhandled IntegrityError. Fix: use select_for_update() or get_or_create().

### Cascade deletes (team decision needed)

Deleting a User wipes courses, students, assessments, enrollments, results, submissions.
Deleting an Enrollment wipes its Results.
Deleting an Assessment wipes its Results.

Should these be PROTECT, SET_NULL, or soft-delete instead?

## Good

Unique constraints present on Result, Course, Student, Enrollment.
Migration drift check runs in CI.

## Still open

Query-count measurements. Needs representative data.
Backup/restore demo. Needs non-production DB.
Index review. Needs real data.
