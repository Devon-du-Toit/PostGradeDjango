PostGradeDjango API Contract
Last updated: 2026-09-30

## Owner Scope

Submission list, summary, and assessment-progress queries are scoped to courses owned by the authenticated user. A list filter that names a nonexistent or other-owner course/assessment returns `400`; retrieving an object outside the owner's scope returns `404`. No endpoint returns another owner's rows.

## Submission List

`GET /api/submissions/`

Filters can be combined:

- `course`: positive integer ID of an owned course.
- `assessment`: positive integer ID of an assessment in an owned course.
- `status`: one of the status values below.
- `search`: case-insensitive search across student number, first name, and last name. Multiple terms can match across the name fields.

Example: `?course=1&status=matched&search=Alice%20Smith&ordering=-created_at`

Ordering accepts `created_at`, `updated_at`, `status`, and `original_filename`, with an optional leading `-` for descending order. The default is `-created_at`; `id` is appended as a deterministic tie-breaker. Unsupported fields return `400`.

Pagination is always enabled. `page` defaults to `1`; `page_size` defaults to `20` and is capped at `100`.

```json
{
  "count": 125,
  "next": "http://127.0.0.1:8000/api/submissions/?page=2",
  "previous": null,
  "results": []
}
```

A positive page number beyond the final page returns `200`, the full matching `count`, and an empty `results` array. Invalid filter values return `400`.

## Pending Verification Summary

`GET /api/submissions/summary/?course=1`

`GET /api/submissions/assessment-progress/?course=1` is a compatibility alias for the same count response.

```json
{
  "needs_verification": 3,
  "matched": 2,
  "pending_verification": 5
}
```

`needs_verification` counts submissions with status `needs_verification`; `matched` counts submissions with status `matched`; `pending_verification` is their sum. These represent submissions awaiting an owner's verification action, not assessment marking progress. Counts include only the authenticated owner's submissions. A supplied `course` must be a positive integer ID for an owned course; a valid owned course with no assessments returns zero counts.

## Assessment Progress

`GET /api/assessments/progress/?course=1` returns one row per owned assessment. `/api/progress/` remains a compatibility alias.

Each row contains `assessment_id`, `course_id`, `name`, `enrolled_count`, `marked_count`, `remaining_count`, and `percent_complete`. `enrolled_count` is the number of students enrolled in the assessment's course; `marked_count` is the number of results recorded for that assessment; `remaining_count` is `max(enrolled_count - marked_count, 0)`; `percent_complete` is the marked-to-enrolled percentage, or `0.0` when there are no enrollments. A supplied course must be owned; invalid, malformed, or other-owner course IDs return `400`.

## Status Values

`uploaded`, `matched`, `needs_verification`, `verified`, `marked`

## Errors

- `400`: invalid filter/query value or a filter referencing a nonexistent or other-owner course/assessment.
- `401`: authentication is required.
- `404`: requested detail object is not found in the owner's scope; malformed or non-positive page values are rejected by page-number pagination.

## Dates and Marks

Submission `created_at` and `updated_at` timestamps are ISO 8601 UTC strings, for example `2026-09-29T19:30:00Z`. Assessment `date` values are calendar dates in `YYYY-MM-DD` format.

Result marks use `DecimalField(max_digits=8, decimal_places=2)` and are serialized as decimal strings, for example `"85.50"`. Comma decimal separators are invalid; marks outside model/business validation return `400`.

## Frontend Rollout

The frontend should send filters, search, ordering, and pagination parameters to the server and consume the paginated `results` envelope. Dashboard verification cards should use the pending-verification summary; assessment completion views should use assessment progress. The summary alias is retained for compatibility while services migrate to `/api/submissions/summary/`.