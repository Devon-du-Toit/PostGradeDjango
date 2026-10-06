# Assessment original-script ZIP export

`GET /api/assessments/{id}/scripts/export/` requires the same authenticated course
owner as the existing assessment and individual-file endpoints. Staff/admin flags
do not grant access to another owner's files. Archived courses or assessments are
unavailable (404). No raw media URL or temporary archive URL is exposed.

The ZIP contains every current submission's original `file` for the selected
assessment, independent of recognition or verification status. Recognition crops
and preview images are excluded. Each entry uses a submission-ID prefix and a
sanitized original basename, preventing path traversal and filename collisions.
The original file bytes are unchanged; submissions and their delivery history are
not modified. A concurrent upload after the metadata snapshot appears on the next
export. If a file disappears during preparation, the entire request fails rather
than returning an incomplete ZIP.

The response is a private, non-cacheable attachment named
`assessment-{id}-scripts.zip`. Preparation copies files in 64 KiB chunks to a
temporary disk file before sending headers. `FileResponse` streams it and closes
the temporary file when the response closes, including disconnected requests.
Preparation failures also close the temporary file. Allow adequate private
temporary-disk space in deployment.

Limits can be configured with `MAX_SCRIPT_EXPORT_FILES` (default 1000) and
`MAX_SCRIPT_EXPORT_BYTES` (default 536870912, 512 MiB of actual source bytes).
Limits are enforced while reading, without trusting storage size metadata.
An empty assessment returns 404 with a clear message; missing originals return
409; exceeding either limit returns 413; disk or storage read failures return 503.
Download individual scripts when an assessment exceeds the ZIP limit.

The companion Vue assessment page offers **Download all scripts (ZIP)**, disables
it for empty lists or an in-progress download, sends the login token through its
existing API client, shows server error messages, and cancels a pending request
when leaving the page.
