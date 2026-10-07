# Permissions and account lifecycle (#8)

This matrix describes the account-lifecycle branch for issue #8. Deploy with its matching Vue update; these changes apply after merge.

How access to the PostGrade API is controlled today, which decisions were made,
and what is deliberately left for later.

## Rule

API endpoints except registration-policy, register, login, refresh and logout need a valid JWT access
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
| `auth/refresh/` | POST | ✓ with a valid refresh token · throttled | – | – | – |
| `auth/logout/` | POST | ✓ possession of a valid refresh token · throttled | – | – | – |
| `auth/registration-policy/` | GET | ✓ returns registration_open | ✓ | ✓ | ✓ |
| `auth/me/` | GET | ✗ | ✓ | ✓ | ✓ |
| `courses/`, `courses/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `courses/{id}/students/` | GET | ✗ | own | own | own |
| `courses/{id}/import-students/` | POST (CSV) | ✗ | own | own | own |
| `courses/{id}/assessments/` | GET POST | ✗ | own | own | own |
| `students/`, `students/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `students/{id}/email/` | POST | ✗ | own | own | own |
| `enrollments/` (also `students/enrollments/`) | GET POST | ✗ | own | own | own |
| `assessments/{id}/` | GET PUT PATCH DELETE | ✗ | own | own | own |
| `submissions/`, `submissions/{id}/` | GET POST PUT PATCH DELETE | ✗ | own | own | own |
| `submissions/verification-queue/` | GET | ✗ | own | own | own |
| `submissions/{id}/verify/`, `.../correct/`, `.../email/` | POST | ✗ | own | own | own |
| `submissions/{id}/file/`, `.../recognition-image/` | GET | ✗ | own | own | own |
| `submissions/{id}/retry-recognition/` | POST | ✗ | own | own | own |
| `assessments/{id}/script-emails/` (+ `approve/`) | GET POST | ✗ | own | own | own |
| `script-emails/{id}/` (+ `approve/`, `retry/`) | GET POST | ✗ | own | own | own |
| `dashboard/stats/`, `dashboard/assessments/` | GET | ✗ | own | own | own |
| Django admin `/admin/` | – | ✗ | ✗ | ✗ | staff users only |

The Marker and Admin columns are identical to Lecturer on purpose: that is
the current behaviour, written down so nobody assumes otherwise.

**Delegated course access** is not supported. On 7 October 2026 the repository owner approved keeping owner-only API access for every role, separate Django staff administration, and no course delegation ([decision #46](https://github.com/Devon-du-Toit/PostGradeDjango/issues/46)). ADMIN, LECTURER and MARKER labels grant no cross-owner API privileges. Numeric marking and gradebooks were removed; marker remains a legacy account label. Any future delegation requires a new approved policy.

## Regression evidence

`accounts.test_permissions` walks every current detail/action route anonymously and as another owner, for all three roles (including a staff/superuser administrator). Tests cover reads, PUT/PATCH/DELETE, nested class lists/assessments, CSV import, protected original/crop files, recognition retry/verification/correction, direct student mail and script email preview/approval/retry. Denied requests must leave domain records, jobs, audits and email state unchanged. List/filter and foreign enrollment tests prevent selection bypasses. Other-owner nested class lists return 404. Deleted grading/gradebook routes are covered separately in distribution's marks-removal tests and are not restored.

## Account lifecycle decisions

| Topic | Implemented policy | Setting |
|---|---|---|
| Signup | Public lecturer signup remains available in development. Production requires explicit opt-in; otherwise a trusted staff administrator creates accounts. Registration-policy reports whether signup is open; Vue hides the signup form when closed. Signup ignores privilege fields and applies Django password validators with user attributes. | ALLOW_REGISTRATION defaults to DEBUG |
| Login throttling | 10 requests per minute per client, including invalid credentials; returns 429 and Retry-After. | LOGIN_THROTTLE_RATE |
| Signup throttling | 5 requests per hour per client. | REGISTER_THROTTLE_RATE |
| Refresh/logout throttling | Separate limits of 30 requests per minute per client each. | REFRESH_THROTTLE_RATE / LOGOUT_THROTTLE_RATE |
| Client identity | REMOTE_ADDR by default; forwarded headers are ignored. Configure trusted proxy depth only if the proxy strips/overwrites untrusted forwarding headers. | NUM_PROXIES defaults to 0 |
| Throttle storage | Shared Django database cache, created by accounts migration 0005. It survives process restarts and is shared by web workers. DRF cache throttles are approximate under concurrent requests; use a perimeter limiter for abuse prevention. | CACHES.throttle / auth_throttle_cache |
| Expiry | Access: 5 minutes. Refresh: 1 day from issuance or last rotation. Rotation renews refresh expiry; no absolute session-duration cap is introduced. | SIMPLE_JWT |
| Rotation | Refresh returns both access and refresh; old refresh is blacklisted. User row locking serializes concurrent refreshes so only one consumes the token. Vue persists the new pair and coordinates one refresh per tab. | ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION |
| Logout | POST auth/logout/ with {"refresh": "..."} blacklists that refresh without requiring a live access token. Vue clears local state immediately and revokes a late rotated response after logout. Previously issued access tokens can remain valid for their remaining 5 minutes. An offline logout cannot guarantee server revocation; Vue reports uncertainty. | Blacklist app + logout route |
| Password reset/deactivation | Trusted staff can use Django admin. Optional self-service recovery uses queued, expiring single-use reset links and configured trusted frontend URLs; production defaults closed. Password changes invalidate access and refresh tokens; disabled/deleted accounts cannot use existing sessions. | CHECK_REVOKE_TOKEN / is_active / [recovery guide](PASSWORD_RECOVERY.md) |
| Browser persistence | Both tokens remain in localStorage for compatibility. This is readable by page scripts and is not an HttpOnly session. Cookie storage and cross-tab coordination require a separate deployment decision. | Vue follow-up #36 |

Register/login/refresh/logout/policy ignore stale bearer headers; domain routes still authenticate access tokens. A refresh token proves possession of one session, not delegated access to another course. Logout does not revoke every device's session. Administrative password resets and deactivation apply to all devices.

DRF throttling is an application limit, not a complete brute-force or denial-of-service defense; its cache updates are not atomic. Hosting must apply rate limits to auth routes and `/admin/login/`, and restrict staff access as appropriate. This is part of the existing [deployment issue #14](https://github.com/Devon-du-Toit/PostGradeDjango/issues/14), rather than claiming API throttles protect Django admin.

## Deployment and client coordination

Deploy the matching Vue auth update first, then migrate/restart the backend. Existing clients that ignore the rotated refresh response will lose their session on the next refresh. Enabling password-bound tokens invalidates sessions issued before this release; users sign in again. Never remove blacklist migrations while valid refresh tokens remain. Schedule `python manage.py flushexpiredtokens` daily to bound outstanding/blacklisted-token history; shared throttle cache entries are culled by Django DatabaseCache.

Set DEBUG=true locally for the requested signup workflow, or ALLOW_REGISTRATION=true explicitly. For public production signup deliberately set ALLOW_REGISTRATION=true; otherwise the production default is closed. No invitation or email-verification policy is silently introduced. Configure NUM_PROXIES only for the actual trusted topology. Endpoint matrix role columns are implemented owner rules, not proposed future role grants.

The Vue update coordinates with [Vue #5](https://github.com/Devon-du-Toit/PostGradeVue/issues/5): one store owns refresh persistence, login failures never trigger a refresh loop, late refresh/user responses cannot restore a logged-out session, and failed refreshes clear state and route to login. Backend owner filters remain the authorization boundary.

## Bounded follow-ups and review

- [Backend #46](https://github.com/Devon-du-Toit/PostGradeDjango/issues/46) is resolved: the owner-only role policy above is approved and covered by the role/endpoint matrix tests.
- Self-service recovery is implemented; enable only after approving frontend URL, SMTP configuration and worker scheduling as described in [PASSWORD_RECOVERY.md](PASSWORD_RECOVERY.md).
- [Vue #36](https://github.com/Devon-du-Toit/PostGradeVue/issues/36): decide HttpOnly refresh cookies, CORS/CSRF policy and coordination across tabs.

Issue #8 also requests a final human review by lSiphonl. Implementation/tests do not constitute that approval; it remains a review step before closing the issue.

Reference: [SimpleJWT rotation, blacklist and password revocation settings](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/settings.html), [DRF throttle behavior and concurrency limits](https://www.django-rest-framework.org/api-guide/throttling/).
