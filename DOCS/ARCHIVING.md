# Course and assessment archiving

DELETE of an owned active course/assessment archives it and returns 204. Subsequent detail/actions return 404. Stored students, enrollments, submissions, originals, recognition crops, verification audits and email history are retained. There is no restore endpoint.

Lists, protected original/crop downloads, verification, recognition retry, script delivery requests and email previews/approval/retry require active parents. Class-list import and enrollment creation reject archived courses. CSV application and upload/delivery creation recheck active parents transactionally.

Archiving cancels queued/running recognition jobs and supersedes unsent script email records. A cancelled worker's late recognition result cannot change the submission. The mail worker excludes archived parents and rechecks before sending. Sent history and attachment snapshots remain. An SMTP send already in progress cannot be recalled; its eventual outcome is recorded.

Global student contact APIs remain available for other active classes. Other assessments are unaffected by archiving one assessment. Archived course keys still participate in owner/code/year/semester uniqueness. Restore, enrollment withdrawal and cascade-retention decisions remain separate work.

Numeric grading, gradebooks and scoring configuration have been removed; see [MARKS_REMOVAL.md](MARKS_REMOVAL.md). Regression coverage is in assessments.tests.test_lifecycle and distribution.tests.test_script_emails.
