# Course and assessment archiving

`DELETE /api/courses/{id}/` and `DELETE /api/assessments/{id}/` archive an
owner's active record and return `204`. Archiving retains students,
enrollments, results, submissions, originals, recognition crops and audit
history. A subsequent request for that archived resource returns `404`.
There is no restore endpoint or administrator force-delete action.

## API behavior

- Lists omit archived courses and assessments and their submissions,
  verification entries and result-email records. Course enrollments are
  hidden when the course is archived. Dashboard
  counts and assessment progress use the same active-parent rules.
- Detail, mutation and action endpoints for those archived workflows
  return `404`, including original/crop downloads, marking, verification,
  recognition retry, result editing and email preview/approval/retry.
- Course student lists, class-list import, course gradebooks and assessment
  statistics reject archived parents. CSV application rechecks and locks
  the course, so a plan validated before archiving cannot later be applied.
- Uploads and writable foreign-key fields reject archived assessments or
  course enrollments with `400` field errors. Course/assessment filters also
  treat archived IDs as invalid choices rather than exposing them.
- An archived assessment is excluded from the calculated course grade.
- Global student records and their owner-scoped contact APIs remain
  available: students can belong to other active courses. Archiving a
  course does not erase or globally disable its students.

## Workers and retention

Archiving runs transactionally with cancellation of queued/running
recognition jobs and superseding unsent result emails in that scope. No
stored script or recognition evidence is deleted. Other assessments remain
active when only one assessment is archived.

Workers exclude archived parents when claiming work and recheck before
processing/delivery. A cancelled recognition job cannot apply a late
result. A claimed email is superseded if its parent is archived before
delivery begins; previously sent emails retain their delivery history.
SMTP already in progress cannot be recalled, and its eventual outcome is
still recorded. Failed sends for archived results are not requeued.

The default model managers retain historical rows. API and worker code use
explicit active-parent queries; this is an archive policy, not an automatic
data purge or a model-level ban on all direct database deletion.

## Remaining lifecycle decisions

Archived course codes still participate in the existing owner/code/year/
semester uniqueness constraint. Restoring/reusing archived course keys,
enrollment withdrawal/removal and changing cascade relationships to
`PROTECT` remain separate decisions. The agreed archive implementation does
not add a lock on assessment `max_mark` or `weight`.

## Verification

`python manage.py test assessments.tests.test_lifecycle` covers retention,
hidden reads/actions, blocked uploads/imports, filter validation, dashboard
counts, cancelled recognition, suppressed email delivery and unaffected
active assessments. The wider domain, submission, worker and mail suites
guard compatibility with active workflows.
