# Current scripts, withdrawal and retained history

## Approved policy

One current verified script per assessment/student membership. Uploads with unknown
identity remain pending. A lecturer's verification activates the newer upload
(created_at, then id as tie-breaker), superseding the older current verified script.
An older upload cannot displace a newer verified one. Identity corrections follow
the same rule. Supersession retains status, original files, audit records, identity
snapshots and delivery evidence. Recognition suggestions alone never activate a
replacement.

Class-only withdrawal retains the enrollment and student contact, including other
class memberships. It hides that membership's scripts from active workflows,
cancels known pending recognition and supersedes unsent delivery. A worker that
had not yet identified a student rechecks current class membership before saving
a suggestion; a withdrawn student cannot be assigned. Explicit class restore
re-enables a previously current verified script, except archived/superseded
scripts. It never revives an old email queue or sends automatically. A lecturer
must explicitly request a new delivery at the new version.

Global student DELETE archives the contact and withdraws every class membership.
It retains the contact's unique student-number key and all enrollment IDs/history.
Explicit contact restore does not restore class memberships: restore each class
separately. New enrollment or CSV import cannot silently restore withdrawn or
archived records. Other lecturers receive 404 for these endpoints.

Course/assessment DELETE retains the existing parent-archive policy. Parent archive
blocks every related read/write/file endpoint; history becomes accessible only
under active parents. Normal ORM hard deletion of referenced users, contacts,
courses, assessments, memberships and submissions is protected. Unreferenced
records can be removed through the ORM; the ordinary API uses archive/withdrawal.
Historical file snapshots/audits/private evidence and delivery records are read
only in admin. No ordinary purge endpoint is provided.

## API contracts

- DELETE `/api/submissions/{id}/` with `{version,reason}`: archive the script, 204.
- GET `/api/submissions/history/?assessment={id}`: paginated owner history,
  including archived/superseded and withdrawn-membership scripts under active
  parents. No mutation, recognition retry or email delivery acts on unavailable
  rows. Fields include `is_active`, `archived_at`, `superseded_at`, `superseded_by`,
  frozen `student_identity`, `file_revisions`, and `audit_entries`.
- Each file revision contains id, version, original_filename, status,
  student_identity, created_at and protected download_url. Revisions share retained
  immutable storage objects; replacement uses a fresh storage key. GET
  `/api/submissions/{id}/revisions/{revision_id}/file/` serves its exact bytes.
- Existing GET `/api/submissions/{id}/file/` and explicit `/history-file/` can serve
  the retained current file for an owned archived/superseded/withdrawn child under
  active parents. Detail/update/verify/retry endpoints still require active rows.
- Original QR page/source endpoints remain protected read-only history evidence.
  All private file responses use `Cache-Control: private, no-store` and vary by
  Authorization. Excluding every QR page clears the current assembled file and
  returns 404 there; the previous file revision and individual originals remain.
- GET `/api/enrollments/?course={id}&include_withdrawn=true` or
  `/api/students/enrollments/` exposes withdrawn memberships for explicit restore.
  Each row includes version, withdrawn_at, withdrawal_reason, student_version and
  student_archived_at, plus existing contact/name fields.
- DELETE `/api/enrollments/{id}/` or `/api/students/enrollments/{id}/` with
  `{version,reason}`: withdraw only this class membership, returns updated row.
- POST either membership endpoint's `/restore/` with `{version,reason}` restores
  it if the contact and course are active. Stale versions/missing reasons fail.
- DELETE `/api/students/{id}/` with `{version,reason}` archives the contact and all
  memberships, 204. POST `/api/students/{id}/restore/` explicitly restores contact.
  GET `/api/students/?include_archived=true` includes owned archived contacts and
  their versions; archived contacts are hidden from the ordinary list.

Audit entries include actor ID plus human actor_name/actor_email (System for null),
timestamp, reason and frozen previous/new identity. User IDs are reference keys,
not human-facing identity labels. Verified file snapshots freeze student number
and name at verification. Historical migration snapshots use the last verified
audit number if available; otherwise `migration_current_reference` labels the
current retained contact. Legacy names are also tagged as current-reference
information: earlier names cannot be reconstructed when they were not recorded.

## Concurrency, migration and rollback

Assessment parent locks serialize activation, replacement, page intake and archive.
All affected recognition jobs are locked in ID order before submissions, then
memberships. Versions and job-attempt leases fence obsolete results. Global contact
archive locks a stable set of class parents and the contact. If a concurrent new
membership commits while archive awaits its contact lock, the operation returns
409 before writes; reload and repeat. No new class's queued script can escape a
successful archive. SMTP already in flight cannot be recalled; its eventual
outcome remains in delivery history. Unsent snapshots are superseded; a claimed
worker rechecks current availability before SMTP.

Migration 0016 freezes pointers/status/identity for every existing nonempty script
file, chooses the latest verified duplicate as current, retains every older row,
adds supersession audits and cancels their queued work. It uses bounded batches
and no document reencoding or blob deletion. A partial database unique constraint
enforces one unarchived, unsuperseded verified script per assessment/enrollment.
QR keys can be reused by a new pending group after an earlier group is archived or
superseded. Withdrawn current QR groups require explicit membership restore
before more pages can be added.

Before migration, back up the database and media together. Schema rollback drops
new revision/availability columns; it is not an evidence-preserving product undo.
Recover the matched database/media backup to restore the full history model.
Normal saves protect frozen revisions/audit identity; raw SQL/queryset mutation
remains an operator responsibility and must not be used to purge history.

CSV lookup/application stay bounded: bare preview is one student lookup; scoped
preview adds one membership lookup. Existing-contact apply adds one withdrawn
membership guard (six queries for 300 unchanged rows, seven for 300 updates),
while 300 entirely new contacts/memberships remain seven queries. Page size does
not add queries to active lists; history uses prefetched revisions and audits.

Synthetic regression tests cover replacement/identity retention, latest-wins
verification races, archive/private history, class/global withdrawal and explicit
restore, key reuse, CSV non-restoration, claimed recognition/delivery, late QR
pages, excluded-page retention, global membership-scope growth and populated
legacy migration. Production/staging deployment and recovery validation remain
outside this change, as requested.

A changed student email also invalidates an unsent snapshot at claim/send checks. Explicitly scheduling again creates a new immutable recipient snapshot; the idempotency key includes a SHA-256 digest of the destination (never the plaintext address), so repeat clicks remain idempotent for the current recipient without reviving the old queue. All lifecycle action bodies must be JSON objects with an integer version and a nonempty reason of at most 2000 characters.

QR assembly also preserves the existing 15 MiB script resource budget via MAX_QR_GROUP_BYTES (default 15728640). Both the sum of included original single-page files and the encoded canonical PDF must fit it. The sum check bounds assembly memory before documents are loaded; shared-resource PDFs can therefore hit this conservative page-file budget before their compact source reaches it. Oversized whole intake returns 413 and rolls back all new rows/blobs, keeping earlier script versions, pages and queued state unchanged. The canonical PDF is encoded once.

Scheduling first reuses any non-superseded snapshot matching the script version, membership and exact recipient, including legacy keys, already-sent records and failed/uncertain deliveries. A return to a previously cancelled destination creates a fresh deterministic target generation and repeat requests reuse it. Earlier cancelled snapshots remain immutable. If the cancelled destination has an unknown delivery outcome, scheduling rejects it for manual review rather than creating a possible duplicate. Key fingerprints use 128 bits of SHA-256 to keep generation keys within the existing 100-character field.
