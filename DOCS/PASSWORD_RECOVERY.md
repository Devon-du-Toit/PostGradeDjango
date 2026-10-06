# Self-service password recovery

Recovery is available locally when `DEBUG=True`. Production is closed by default.
Enable `ALLOW_PASSWORD_RECOVERY=true` and configure `PASSWORD_RESET_FRONTEND_URL`
to the approved HTTPS frontend `/reset-password` page (no query, fragment or URL
credentials). The default local URL is `http://localhost:5173/reset-password`.
The configured URL is trusted deployment configuration, never the request Host.
Configure the existing Django email backend/SMTP credentials and from address;
this change selects no production provider or deployment hostname.

Apply `python manage.py migrate` (accounts migration 0006). Request links with
`POST /api/auth/password-reset/` and `{ "email": "..." }`. Every syntactically valid
address receives the same 202 message and a queue row, including unknown and
disabled accounts. SMTP delivery happens outside the public request, so SMTP
latency and failure cannot reveal account existence. The auth policy endpoint
returns `password_recovery_available`; both reset endpoints fail closed with 403
when recovery is disabled or the configured URL is invalid.

Run `python manage.py send_password_resets --limit 100` regularly through the
deployment's existing worker/scheduler. For local testing, run it after requesting
a link and inspect a development mailbox. Use the locmem backend in automated
tests; avoid printing real reset links to a shared console or logging them.
The worker sends only to exactly one active account with a usable password.
Ambiguous legacy case-variant email aliases receive no link. It locks queue
rows and users, skips claimed work, and deletes handled/unknown requests. Delivery
failures retry after two and four minutes, with at most three attempts. Requests
older than one hour are deleted even if recovery is disabled; cleanup requires
the command to keep running. Queued email addresses are private account data;
restrict database access. Tokens and passwords are never stored in this queue.
SMTP connections time out after ten seconds. Delivery errors deliberately emit
no exception text or account identifiers; monitor queue age/count instead.

Links carry a Django password-bound token and encoded user ID in a URL fragment,
which browsers do not send to the frontend HTTP server or its access logs. Tokens expire after
one hour, are invalidated by successful password change, and are checked again
under the user row lock before consumption. New passwords use Django's configured
validators and user attributes. Concurrent consumption has one winner. Pending
requests created before a successful reset are discarded, preventing an old
queued request from generating a fresh link afterward. Previously issued links
remain usable until password change/expiry; requesting another link alone does
not invalidate them. Old access and refresh JWTs are rejected by the existing
password-hash revocation checks.

`POST /api/auth/password-reset/confirm/` accepts `uid`, `token`, and `password`.
Invalid, expired, reused, unknown, and disabled-account links return the same 400
invalid-link message. Request and confirmation rates default to five/hour and
ten/hour per client; request throttling also applies to a hash of the normalized
email address. Configure `PASSWORD_RESET_THROTTLE_RATE`,
`PASSWORD_RESET_CONFIRM_THROTTLE_RATE`, and trusted proxy depth as needed.

Vue exposes Forgot password and Reset password screens. It removes link credentials
from browser history after reading them, clears local sessions after successful
reset, and sends no JWT or automatic refresh for recovery calls. Keep reset URLs,
password bodies and query strings out of frontend proxy/access/analytics/error
logs. The application uses a no-referrer browser policy. Confirm the trusted URL,
SMTP delivery, worker scheduling and private log handling before opting in on a
production deployment; staging/deployment work remains separate.
