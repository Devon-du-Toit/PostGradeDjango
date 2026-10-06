# QR script intake and review

Configure an assessment with `expected_qr_page_labels: ["P1", "P3"]` and
`qr_test: "KT2"`; its course code and optional assessment date validate the other
printed fields. An empty label list preserves the existing single-script upload
workflow. Labels must be unique positive P numbers; they need not be contiguous.
QR configuration/date become immutable after QR intake. This prevents changing
completion rules beneath existing reviewed scripts.

POST the existing authenticated `/api/submissions/` upload with assessment,
file and recognition_method (`ocr` or `bubble`). All PDF/image pages are inspected.
The five QR fields are module, YYYYMMDD date, test, P label and # test number.
The grouping key excludes the page label. QR never supplies student identity.
One mixed upload can produce several submissions; the response retains the
normal submission shape and additionally returns `upload_group_ids`. Fetch each
ID through the existing detail endpoint or assessment-filtered list. Repeated
intake for the same assessment/group appends pages, without silently dropping
repeated labels. Existing configured upload size/page limits still apply; split
large scanner batches into uploads of at most the configured page limit (20 by
default).

`grouped_pages` exposes parsed fields, QR status, numeric label order, recognition
outcome/quality issues, suggested and linked enrollments, private page and source
URLs, exclusions and audited review history. `qr_metadata` identifies the paper
group. `qr_review_issues` records missing, duplicate, unexpected, unreadable,
invalid, conflicting-test or conflicting-student findings. `qr_group_status` is
manual_review, pending_identification or linked. No raw storage URL is exposed.
Per-page recognition uses the selected OCR/bubble method and records failures
without losing readable QR grouping. A single clear page may suggest an enrollment;
contradictory page suggestions block verification. A lecturer must verify the
identity before all included pages are linked to that enrollment. Selecting an
enrollment contrary to a sole recognition suggestion requires a review reason.

The submission download is a canonical PDF containing ONLY this group's full
original pages in P-number order, including vector PDF content. Original images
are embedded intact into a PDF page. The source upload is retained separately as
private evidence and can contain multiple groups: never use it as a student email
attachment. Emails use the canonical group PDF. Excluded duplicates retain their
original page and source evidence but leave the canonical PDF. Incomplete or
conflicted groups cannot be verified or emailed.

A late page invalidates the prior identity/version, clears page links, cancels
older recognition jobs and supersedes unsent delivery snapshots. The group must
complete recognition and renewed lecturer verification before another delivery.
Parent locks serialize intake, page review and verification; worker updates are
fenced by the captured submission version. A cancelled older worker cannot update
current page suggestions. Previously sent email snapshots remain immutable.

## Private endpoints

- GET `/api/submissions/{id}/pages/{page_id}/file/`: original full single-page PDF.
- GET `/api/submissions/{id}/uploads/{upload_id}/file/`: original source upload.
- POST `/api/submissions/{id}/pages/{page_id}/review/`: explicit grouping repair.

All endpoints require the owning lecturer and active course/assessment. Other
owners receive 404. Recognition does not grant public file access.

Page review requires current `version` and nonempty `reason`. Optional fields:
`qr_value` supplies a manually checked five-field QR value; `exclude` is a boolean
for an explicitly reviewed duplicate/unwanted page; `reviewed_enrollment` is a
current assessment-course enrollment ID (or null to dismiss a conflicting
suggestion). For moving a page, also provide `destination_submission` and that
group's `destination_version`. Metadata must match the destination and assessment.
An unreadable page needs a corrected QR before it can move into a known group.
Every review stores actor, timestamp, original/corrected metadata, grouping,
exclusion and prior/new identity suggestion. Review invalidates identity/delivery
and leaves affected groups needing renewed verification. No original page is
removed from storage by review. Normal PUT/PATCH file replacement is rejected for
QR groups; intake and page review preserve their page-level evidence.

Example duplicate exclusion:

```json
{"version": 2, "reason": "Lecturer confirmed this is a duplicate scan", "exclude": true}
```

Example unreadable-page repair and move:

```json
{"version": 1, "destination_submission": 42, "destination_version": 3,
 "reason": "Lecturer checked the printed module/date/test/page fields",
 "qr_value": "CMPG211,20230412,KT2,P3,#1"}
```

## Validation evidence

Synthetic tests cover actual QR PDF decoding, scrambled two-group scans, page
arrival before identity, unclear recognition, missing/duplicate/unexpected labels,
wrong test metadata, unreadable QR repair, conflicting students, duplicate
exclusion, protected downloads, version/reason checks, rollback file cleanup and
parallel intake/verification/obsolete recognition. Tests contain no student scans.
The first four pages of the supplied 520-page KT2 template were evaluated locally:
P1/#1 and P3/#1 share a key, P1/#2 and P3/#2 share a different key. Original scans
remain local; the committed evidence contains only printed paper QR metadata.
The 520-page source exceeds the upload limit and is not an upload-sized fixture.
Run `python manage.py test submissions.tests.test_qr_grouping`.

Frontend issue PostGradeVue#21 can consume upload_group_ids/grouped_pages and the
page-review endpoints; no folder-per-student workflow is required.

QR page prefetch adds one bounded query to list/queue APIs: five queries with forced authentication (six with real JWT), independent of page size. The database review harness budgets include this page query; the older committed database-review evidence records the pre-QR baseline.

Cumulative intake is capped at MAX_QR_GROUP_PAGES (default 100), including excluded duplicates retained in a group. Exceeding it rejects the entire upload with 400, preserving all previous pages/versions/delivery state. This prevents repeated uploads from creating an unbounded canonical rebuild. QR rendering is capped at a 6000-pixel longest side; default page/byte limits continue to apply to each incoming upload.
