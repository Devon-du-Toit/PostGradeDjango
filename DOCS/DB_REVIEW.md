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

### Model vs serializer validation

Result.clean(), Enrollment.clean(), and Submission-related clean() methods enforce things like course match, owner match, and mark <= max_mark. These run on full_clean(), not on save().

The DRF serializer does not call full_clean(). So values that come in through the API can be saved without those checks running, unless the serializer re-implements them.

Decision needed: replicate the model validations in the serializer, call full_clean() from the serializer's validate(), or move the constraints into the database where they cannot be bypassed.

## Good

Unique constraints present on Result, Course, Student, Enrollment.
Migration drift check runs in CI.

## Still open

Query-count measurements. Needs representative data.
Backup/restore demo. Needs non-production DB.
Index review. Needs real data.

### Duplicate submissions (decision needed)

There is no uniqueness constraint preventing the same enrollment from submitting twice for the same assessment. Django currently allows it. The Vue client does not warn about it either.

Decision needed: reject duplicates at the model level, allow but flag them for review, or allow freely.
