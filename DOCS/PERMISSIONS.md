# Permissions and account lifecycle (#8)

Release integration documentation. The implementation must reach `master` before these release rules apply there; see [API reference integration status](API_REFERENCE.md#14-release-integration-status).

How access to the PostGrade API is controlled today, which decisions were made,
and what is deliberately left for later.

## Rule

API endpoints except register, login and refresh need a valid JWT access
token. Health probes at `/health/live/` and `/health/ready/` require no JWT;
Django admin uses its staff session. Every domain object belongs to one
lecturer (`owner`), and normal domain queries are
filtered by the logged-in user, so another lecturer's data answers **404**
(never 403, which would confirm it exists).

`User.role` (`ADMIN`, `LECTURER`, `MARKER`) is stored and returned by
`/api/auth/me/`, but **it is not used for authorization**. Showing a role in
the frontend must not be treated as a permission check.

## Endpoint matrix

Legend: **✓** allowed · **own** only objects the user owns (others → 404) ·
**✗** refused (401 without a token).

| Endpoint | Methods | Anonymous | Lecturer | Marker | Admin |
|---|---|---|---|---|---|
| `auth/register/` | POST | ✓ when registration is open, else 403 · throttled | – | – | – |
| `auth/login/` | POST | ✓ throttled | – | – | – |
| `auth/refresh/` | POST | ✓ with a valid refresh token | – | – | – |
| `auth/me/` | GET | ✗ | ✓ | ✓ | ✓ |
| `courses/`, `courses/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `courses/{id}/students/` | GET | ✗ | own | own | own |
| `courses/{id}/import-students/` | POST (CSV) | ✗ | own | own | own |
| `courses/{id}/assessments/` | GET POST | ✗ | own | own | own |
| `courses/{id}/gradebook/` | GET | ✗ | own | own | own |
| `students/`, `students/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `students/{id}/email/` | POST | ✗ | own | own | own |
| `enrollments/` (also `students/enrollments/`) | GET POST | ✗ | own | own | own |
| `assessments/{id}/`, `.../statistics/` | GET PUT PATCH DELETE | ✗ | own | own | own |
| `assessments/{id}/results/`, `results/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `submissions/`, `submissions/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `submissions/verification-queue/` | GET | ✗ | own | own | own |
| `submissions/{id}/verify/`, `.../mark/` | POST | ✗ | own | own | own |
| `submissions/{id}/file/`, `.../recognition-image/` | GET | ✗ | own | own | own |
| `submissions/{id}/retry-recognition/` | POST | ✗ | own | own | own |
| `assessments/{id}/result-emails/` (+ `approve/`) | GET POST | ✗ | own | own | own |
| `result-emails/{id}/` (+ `approve/`, `retry/`) | GET POST | ✗ | own | own | own |
| `dashboard/stats/`, `dashboard/assessments/` | GET | ✗ | own | own | own |
| Django admin `/admin/` | – | ✗ | ✗ | ✗ | staff users only |

The Marker and Admin columns are identical to Lecturer on purpose: that is
the current behaviour, written down so nobody assumes otherwise.

**Delegated course access** (a marker working on a lecturer's course) is
**not supported**. It needs a course-membership model and changes to every
owner filter, so it is a follow-up (F1), not a gap in the current scope.

## Verified

- Cross-owner probe of all reads, writes, deletes, file downloads, CSV
  import, gradebook, statistics, recognition and email actions: a second
  lecturer gets 404/400 and nothing changes (review comment on #8).
- `courses/{id}/students/` for another lecturer's course now answers 404
  like the other nested routes (it used to answer `200` with an empty list).
- Registration cannot set `role` (not in the serializer), so signup cannot
  grant privileges.

## Account lifecycle decisions

| Topic | Decision | Setting |
|---|---|---|
| Signup | Open in development, **closed in production** unless enabled. When closed, an administrator creates lecturer accounts in Django admin. | `ALLOW_REGISTRATION` (default: `DEBUG`) |
| Login throttling | 10 attempts per minute per client; then `429` with `Retry-After`. | `LOGIN_THROTTLE_RATE` |
| Registration throttling | 5 per hour per client. | `REGISTER_THROTTLE_RATE` |
| Client identity behind a proxy | Only trusted proxies are counted, so a client cannot dodge the limit with a fake `X-Forwarded-For` header. Behind the hosting proxy set `NUM_PROXIES=1`, otherwise every user shares one limit. | `NUM_PROXIES` (default 0) |
| Throttle storage | Shared database cache table (`throttle_cache`, created by `migrate`), so the limit holds across all web processes. Only login and register touch it. | `CACHES["throttle"]` |
| Token expiry | SimpleJWT defaults: access token 5 minutes, refresh token 1 day. The frontend refreshes automatically. | — |
| Token revocation / logout | Not supported: logout only deletes tokens in the browser; a stolen refresh token stays valid for up to 1 day. | F3 |
| Password recovery | Not supported; an administrator resets passwords in Django admin. Needs the production email provider (#14). | F2 |

## Follow-ups (bounded, to be opened as issues)

- **F1 Role-based authorization and delegated course access.** Decide what
  a marker may do (e.g. verify but not delete), whether markers join a
  lecturer's course, and what an admin may see. Then enforce it in the
  API, not just in the UI.
- **F2 Password reset by email.** After the email provider is chosen (#14).
- **F3 Server-side logout.** Enable SimpleJWT's token blacklist and refresh
  token rotation; blacklist the refresh token on logout.
- **F4 Token storage in the browser.** Tokens are in `localStorage`
  (readable by any script on the page). Moving the refresh token to an
  HttpOnly cookie must be done together with the Vue auth ticket (Vue #5).
