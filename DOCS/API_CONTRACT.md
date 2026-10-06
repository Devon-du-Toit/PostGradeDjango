# PostGrade API contract

All protected routes require JWT and expose only the authenticated owner's active scopes. Detail/action probes of another owner return 404; invalid related-object filters return 400. Archived parents are excluded from normal lists and workers.

## Lists

List responses are `{count,next,previous,results}`. Default page size 25, maximum 100. Empty first page: 200/count 0; beyond the last page: 404. Search/filtering precede pagination. Server ordering uses a unique tie-breaker.

| List | Filters | Search | Ordering |
|---|---|---|---|
| courses | year, semester | code, name | newest year/semester, code, id |
| course assessments | owned course in path | name | date, name, id |
| students | course | student number/name/email | student number, id |
| enrollments | course, student | student number/name | course, student number, id |
| submissions | course, assessment, status | filename/student number/name | newest created_at, id |
| verification queue | course, assessment, status | filename/student number/name | oldest created_at, id |
| assessment script-emails | status | recipient/student number/name | newest created_at, id |
| dashboard assessments | course | assessment/course names/code | newest date (null last), id |

Status accepts comma-separated valid values; one invalid value rejects the complete filter. Submission statuses: uploaded, processing, matched, needs_verification, recognition_failed, verified. The global queue and pending count currently include matched and needs_verification only; failed scripts remain accessible through assessment submissions.

## Enrollment and assessment records

Enrollment records include id, course, student, created_at and read-only student_number/first_name/last_name. Verification choices come from owned course enrollments, not a gradebook. Assessments have name and optional date; max_mark, weight and numeric results are removed.

Dates use YYYY-MM-DD or null; timestamps use ISO 8601. Student numbers remain strings, including leading zeros. Delivery versions and submission versions are integers, not grades.

## Dashboard

Stats expose active_courses for the current Django local calendar year, pending_verifications and all submission-status counts. Paginated progress includes id, name, date, course, course_code, enrolled, submissions and submissions_by_status. Results counts and score summaries no longer exist.

## Mutation and delivery contract

Verification is transactional; an unchanged repeated enrollment does not increment version. Generic edits cannot change assessment/enrollment. Replacing a file requires the current version, clears verification and supersedes unsent deliveries. Email requests are explicit and idempotent per verified version. Messages attach a private immutable copy of that verified file and send to one student. Approval/retry operate only on current verified records; unknown delivery needs JSON boolean confirmation.

See [SCRIPT_EMAIL_DELIVERY.md](SCRIPT_EMAIL_DELIVERY.md), [ARCHIVING.md](ARCHIVING.md) and [MARKS_REMOVAL.md](MARKS_REMOVAL.md). The old marking/results/gradebook/statistics/result-email paths return 404.
