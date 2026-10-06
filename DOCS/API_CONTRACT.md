# PostGrade API Contract

Release integration reference · updated 2026-10-06

See [API_REFERENCE.md §14](API_REFERENCE.md#14-release-integration-status):
archive (#39) and failed-recognition queue (#41) rules below require their
code to be integrated into master. Pagination itself is already merged.

## Authentication and Ownership

All list and dashboard endpoints require JWT authentication using `Authorization: Bearer <access_token>`. Responses are scoped to the authenticated user's data. Invalid or other-owner course/assessment/student filters return `400`; detail routes scoped to another user's object return `404`.

## Pagination

DRF's `StandardPagination` applies to list endpoints:

- `page` defaults to `1`.
- `page_size` defaults to `25` and is capped at `100`.
- Responses contain `count`, `next`, `previous`, and `results`.
- An empty first page returns `200` with `results: []` and `count: 0`.
- A page beyond the final page returns `404`.

Example:

```json
{
  "count": 42,
  "next": "http://127.0.0.1:8000/api/submissions/?page=2",
  "previous": null,
  "results": []
}
```

`next` and `previous` are URLs to the corresponding page, or `null` when there is no such page.

## List Endpoints

| Endpoint | Scope and filters | Search | Stable server ordering |
| --- | --- | --- | --- |
| `GET /api/courses/` | Authenticated user's courses; optional `year`, `semester` | Course `code`, `name` | `-year`, `-semester`, `code`, `id` |
| `GET /api/courses/{course_id}/assessments/` | Assessments for an owned course | Assessment `name` | `date`, `name`, `id` |
| `GET /api/courses/{course_id}/students/` | Students enrolled in an owned course | Student number, first name, last name, email | Student number, `id` |
| `GET /api/students/` | Authenticated user's students; optional owned `course` | Student number, first name, last name, email | Student number, `id` |
| `GET /api/enrollments/` and `GET /api/students/enrollments/` | Enrollments for owned course/student; optional `course`, `student` | Student number, first name, last name | Course ID, student number, `id` |
| `GET /api/assessments/{assessment_id}/results/` | Results for an assessment in an owned course | Student number, first name, last name | Student number, `id` |
| `GET /api/submissions/` | Owned submissions; optional `course`, `assessment`, `status` | Filename, student number, first name, last name | `-created_at`, `-id` |
| `GET /api/submissions/verification-queue/` | Owned submissions whose status is `needs_verification`, `matched` or `recognition_failed`; optional `course`, `assessment`, `status` | Filename, student number, first name, last name | `created_at`, `id` |
| `GET /api/dashboard/assessments/` | Assessments in owned courses; optional owned `course` | Assessment name, course code, course name | Assessment date descending (undated last), `-id` |

These endpoints do not expose a client-selectable `ordering` parameter. Ordering is chosen by the server and includes a unique tie-breaker for stable pagination.

## Submission Filters and Search

`course` must identify a course owned by the authenticated user. `assessment` must identify an assessment in an owned course. `status` accepts one or more comma-separated submission status values, for example `?status=matched,marked`. Multiple filters and `search` can be combined; filters narrow the result set together.

Search is case-insensitive and matches any configured search field. The submission list and verification queue search original filename, student number, first name, and last name. A filename search can therefore find a submission that has not been matched to a student.

The release verification queue is restricted to `needs_verification`, `matched` and `recognition_failed`; other status values are invalid for that endpoint. Until the #41 stack reaches master, that branch still has only the first two queue statuses.

## Submission Status Values

`uploaded`, `processing`, `matched`, `needs_verification`, `recognition_failed`, `verified`, `marked`

`pending_verifications` uses the same release queue statuses: `needs_verification`, `matched` and `recognition_failed`. It excludes `processing`, `verified` and `marked`. Once #39 is integrated, all counts and normal lists also exclude archived courses/assessments. Archived IDs are invalid choices for course/assessment filters; detail/action routes return 404. See [ARCHIVING.md](ARCHIVING.md).

## Dashboard Responses

### `GET /api/dashboard/stats/`

Returns counts scoped to the authenticated user:

- `active_courses`: unarchived courses whose year is the current Django local calendar year (the current TIME_ZONE is UTC).
- `pending_verifications`: submissions in the verification-queue statuses.
- `submissions_by_status`: count for every submission status, including zero-count statuses.

### `GET /api/dashboard/assessments/`

Returns a paginated list of the user's assessments. Each result includes `id`, `name`, `date`, `max_mark`, `course`, `course_code`, `enrolled`, `submissions`, `submissions_by_status`, and `results_recorded`. `enrolled` is the number of enrollments in the course; `results_recorded` is the number of results for that assessment; `submissions` is the total submission count for that assessment; `submissions_by_status` provides counts by submission status.

## Dates and Decimal Values

Date fields use ISO `YYYY-MM-DD` format, or `null` when optional. Datetime fields such as `created_at` and `updated_at` are ISO 8601 timestamps with UTC offset information.

Assessment `max_mark`, assessment `weight`, and result `mark` are decimal values with two fractional digits. Result marks use `DecimalField(max_digits=8, decimal_places=2)` and are serialized as decimal strings, for example `"85.50"`. Calculated percentages and custom gradebook/statistics response values are JSON numbers; format display precision in the client. Marks must be non-negative and cannot exceed the assessment maximum; invalid marks return `400`.

## Errors

- `400 Bad Request`: invalid filter values, malformed comma-separated status values, or filters naming nonexistent or other-owner related objects.
- `401 Unauthorized`: missing or invalid authentication credentials.
- `404 Not Found`: detail object outside the authenticated user's scope, unknown route/object, or requested page beyond the last page.
