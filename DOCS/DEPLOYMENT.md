# Deployment and Operations Runbook

PostGrade — Group 13

Version 0.1.0

## Revision History

| Date | Version | Description | Author |
|---|---|---|---|
| 01/10/2026 | 0.1.0 | Container image, target environment, configuration, first deployment, operations, backup and rollback (Issue #14). | Graham Robert |

## Table of Contents

1. [Introduction](#1-introduction)
2. [Architecture](#2-architecture)
3. [Target Environment](#3-target-environment)
4. [Configuration Reference](#4-configuration-reference)
5. [Building and Running Locally](#5-building-and-running-locally)
6. [First Deployment](#6-first-deployment)
7. [Operations](#7-operations)
8. [Backups](#8-backups)
9. [Releasing and Rolling Back](#9-releasing-and-rolling-back)
10. [Staging Acceptance Check](#10-staging-acceptance-check)
11. [Troubleshooting](#11-troubleshooting)
12. [Issues List](#12-issues-list)

---

## 1. Introduction

### 1.1 Purpose

How to build, configure, deploy and operate the PostGrade backend: the API, the recognition worker and the mail worker.

### 1.2 Scope

In scope: the container image, environment configuration, HTTPS and proxy settings, the database, private media storage, the workers, health checks, logs, backups and rollback.

Out of scope: building and hosting the Vue frontend (see the frontend README, *Environment Configuration*), except where the two must agree (Section 6.4).

### 1.3 Requirement Traceability

| Requirement | Section |
|---|---|
| #14 — choose and document the target environment, server, HTTPS/proxy, database, media storage and workers | 2, 3 |
| #14 — environment-managed secrets, production settings, deployment checks, CORS and allowed hosts | 4, 6 |
| #14 — health/readiness, structured logs without student-document contents, job/email failure visibility | 7 |
| #14 — backups and rollback | 8, 9 |
| #14 — staging upload → verification → script delivery with sandbox email | 10 |

---

## 2. Architecture

One container image runs in three roles. The container command decides the role.

| Role | Command | Needs | Scale |
|---|---|---|---|
| **web** (API) | `gunicorn config.wsgi:application --config config/gunicorn.conf.py` (image default) | database, media (read/write) | 1+ |
| **recognition-worker** | `python manage.py run_recognition_worker` | database, media (read/write) | 1–2 (see 7.4) |
| **mail-worker** | `python manage.py run_mail_worker` | database, SMTP | exactly 1 is enough |
| **migrate** (one-off) | `python manage.py migrate --noinput` | database | runs before each release |

```
   Browser ──HTTPS──▶ Reverse proxy (TLS) ──HTTP──▶ web (gunicorn, 3 processes)
                                                     │         │
                              PostgreSQL ◀───────────┘         ▼
                                  ▲   ▲                media volume (scripts, crops)
             recognition-worker ──┘   │                      ▲
                     └────────────────┼──────────────────────┘
                   mail-worker ───────┘──▶ SMTP provider
```

The workers take jobs from database tables (`RecognitionJob`, `ScriptEmail`); there is no separate message broker. The web role and the recognition worker must see **the same media storage**: the web role saves uploads and serves downloads; the worker reads the upload and saves the recognition crop.

### 2.1 Image

`Dockerfile`, built from the repository root:

- `python:3.12-slim` plus the system libraries OpenCV and PaddlePaddle load at runtime.
- Runs as the unprivileged user `app` (uid 1000). The code is owned by root, so the application cannot modify itself; it writes only to `/tmp` and the media volume (`/data/media`).
- The OCR models (~140 MB) are downloaded at **build** time, so a new container never downloads them during a recognition.
- Django admin's static files are collected at build time (`/app/staticfiles`).
- Size: about 3.2 GB (PaddlePaddle and OpenCV).

### 2.2 Measured resource use

Measured on 1 October 2026 with `docker compose up` and one real script recognised end to end:

| Container | Memory | Notes |
|---|---|---|
| web (3 gunicorn processes) | ~500 MB | Each process currently imports PaddleOCR at startup (planned fix: load it only in the worker). |
| recognition-worker | ~170 MB idle, ~715 MB peak | Peak while recognising; models load on the first job. |
| mail-worker | ~170 MB | |
| PostgreSQL | ~65 MB | Small demo dataset. |
| **Total** | **~1.5 GB peak** | A host with **4 GB RAM and 2 vCPUs** leaves comfortable headroom. |

One script took **91 s** from upload to `matched`, including the worker's first model load; later scripts skip the load.

---

## 3. Target Environment

### 3.1 Decision

> **Status: proposed — to be confirmed by the team (review meeting, 2 October 2026).**

| Concern | Choice |
|---|---|
| Hosting | One Linux virtual machine (Ubuntu LTS, 2 vCPU / 4 GB), e.g. on Azure for Students |
| Runtime | Docker Engine + Docker Compose, using this repository's `docker-compose.yml` plus a server-only override file (Section 6.2) |
| Production server | gunicorn (Section 2) |
| HTTPS / proxy | Caddy on the VM: automatic Let's Encrypt certificates, HTTP → HTTPS redirect, forwards to `web` |
| Database | PostgreSQL 17 container with a persistent volume, nightly `pg_dump` (Section 8) |
| Private media | Docker volume `media` mounted at `/data/media` in web and recognition-worker; never served directly, only through the owner-checked download endpoints |
| Workers | `recognition-worker` and `mail-worker` containers with `restart: unless-stopped` |
| Frontend | Built Vue files served by the same Caddy, with the API under `/api/` on the same domain |
| Email | A transactional SMTP provider; a **sandbox** account for staging (Section 10) |

### 3.2 Why

- It is exactly the stack tested on 1 October 2026 (Section 2.2), so the first deployment has no untested parts.
- One machine fits the measured load with headroom and the course budget.
- Serving the frontend and API from one domain removes CORS from the picture and lets the frontend use `VITE_API_BASE_URL=/api/`.

### 3.3 Alternatives considered

| Option | For | Against |
|---|---|---|
| **Managed containers** (e.g. Azure Container Apps) + managed PostgreSQL + network file share for media | Automatic restarts and scaling, managed backups, no server patching | More setup and cost; media must move to a shared file share; untested |
| **Platform-as-a-service without containers** | Little setup | PaddlePaddle's system libraries and memory needs fit poorly; workers need separate processes |

The managed-containers option is the natural next step after UAT. Because everything is configured through environment variables and the image already separates the three roles, moving needs no code changes except, eventually, a cloud storage backend for media (Issue 03).

---

## 4. Configuration Reference

All configuration comes from environment variables; nothing secret is committed. `.env.example` lists the same variables with comments.

### 4.1 Required in production

| Variable | Example | Notes |
|---|---|---|
| `SECRET_KEY` | 50+ random characters | Startup fails if missing. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. Never reuse the development key. |
| `DEBUG` | `False` | Must be false: true exposes stack traces and settings. |
| `ALLOWED_HOSTS` | `postgrade.example.com` | Comma-separated host names the API answers to. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | | PostgreSQL connection. |
| `CSRF_TRUSTED_ORIGINS` | `https://postgrade.example.com` | Needed for Django admin forms over HTTPS. |
| `SECURE_SSL_REDIRECT` | `true` | Redirect HTTP to HTTPS (health checks are exempt). |
| `NUM_PROXIES` | `1` | Number of proxies in front of the app (Caddy = 1). With `0`, every user shares one login-throttle limit. *(Added in #8.)* |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | The default prints emails to the console. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | | SMTP provider. |

### 4.2 Optional

| Variable | Default | Notes |
|---|---|---|
| `SECURE_HSTS_SECONDS` | `0` | Set `31536000` only after HTTPS has worked for a while: browsers then refuse plain HTTP for a year. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Only needed when the frontend is on a **different** domain. |
| `DB_CONN_MAX_AGE` | `0` | Seconds to reuse database connections. Production: `60`. |
| `MEDIA_ROOT` | `/data/media` in the image | Where uploads and crops are stored. |
| `SCRIPT_EMAIL_RELEASE_POLICY` | `automatic` | `approval` holds emails until a lecturer approves them. |
| `LOGIN_THROTTLE_RATE`, `REGISTER_THROTTLE_RATE` | `10/min`, `5/hour` | *(Added in #8.)* |
| `LOG_FORMAT`, `LOG_LEVEL` | `json` (when not DEBUG), `INFO` | |
| `WEB_CONCURRENCY` | `3` | gunicorn processes in the web container. ~2 per vCPU. |
| `GUNICORN_TIMEOUT` | `60` | Seconds before a stuck request is killed. Uploads of up to 15 MB fit. |

### 4.3 Deployment check

Run against the production configuration before every first deployment and after configuration changes:

```bash
docker compose run --rm web python manage.py check --deploy
```

Expected result: no warnings. On a local stack (plain HTTP) three are expected: `W004` (HSTS), `W008` (SSL redirect) and `W009` if the local `SECRET_KEY` is short.

---

## 5. Building and Running Locally

Requires Docker Desktop (Windows: WSL 2 with *Virtual Machine Platform* enabled).

```bash
# .env must contain SECRET_KEY (the other values in docker-compose.yml are local-only)
docker compose up --build -d
docker compose ps            # web "healthy", migrate "Exited (0)"
curl http://localhost:8000/health/ready/
docker compose logs -f web recognition-worker
docker compose down          # keeps the database and media volumes
```

The first build takes a long time (PaddlePaddle, OpenCV and the OCR models); later builds reuse the cached layers unless `requirements.txt` changes. All four services share the image `postgrade-backend:local`, so it is built once.

---

## 6. First Deployment

### 6.1 Server

1. Create the VM (Section 3.1) and point a DNS name at it (a cloud provider's default DNS name works).
2. Open ports **80** and **443** only. Do not expose 5432 (PostgreSQL) or 8000 (gunicorn).
3. Install Docker Engine with the Compose plugin, and Caddy.
4. `git clone` the repository to `/opt/postgrade` (the folder name becomes the Compose project name, so the volumes are `postgrade_pgdata` and `postgrade_media`).

### 6.2 Configuration on the server

Create `.env` (secrets, never committed):

```bash
SECRET_KEY=...generated...
DB_PASSWORD=...generated...
EMAIL_HOST=...
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
```

Create `docker-compose.override.yml` next to `docker-compose.yml`. Compose merges it automatically, and it replaces the local-only values:

```yaml
x-production: &production
  SECRET_KEY: ${SECRET_KEY}
  ALLOWED_HOSTS: postgrade.example.com
  CSRF_TRUSTED_ORIGINS: https://postgrade.example.com
  SECURE_SSL_REDIRECT: "true"
  NUM_PROXIES: "1"
  DB_PASSWORD: ${DB_PASSWORD}
  EMAIL_BACKEND: django.core.mail.backends.smtp.EmailBackend
  EMAIL_HOST: ${EMAIL_HOST}
  EMAIL_HOST_USER: ${EMAIL_HOST_USER}
  EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD}
  DEFAULT_FROM_EMAIL: PostGrade <noreply@postgrade.example.com>

services:
  db:
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    restart: unless-stopped
  migrate:
    environment: *production
  web:
    environment: *production
    ports: !override
      - "127.0.0.1:8000:8000"   # only Caddy on this machine can reach it
    restart: unless-stopped
  recognition-worker:
    environment: *production
    restart: unless-stopped
  mail-worker:
    environment: *production
    restart: unless-stopped
```

`.env` and the override file stay on the server; keep a copy of `.env` in the team's password manager.

### 6.3 HTTPS proxy

`/etc/caddy/Caddyfile`:

```
postgrade.example.com {
    encode gzip

    # API, admin and health checks go to gunicorn
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle /admin/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle /health/* {
        reverse_proxy 127.0.0.1:8000
    }

    # Everything else is the Vue app, with the SPA fallback
    handle {
        root * /srv/postgrade-frontend
        try_files {path} /index.html
        file_server
    }

    request_body {
        max_size 20MB   # uploads are limited to 15 MB by the API
    }
}
```

Caddy obtains and renews the certificate, redirects HTTP to HTTPS, and sets `X-Forwarded-Proto` and `X-Forwarded-For` itself, ignoring any values sent by the client. That matters: Django trusts `X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`) and the login throttle trusts one `X-Forwarded-For` hop (`NUM_PROXIES=1`). **Never expose gunicorn directly** with these settings, or clients could forge both headers.

### 6.4 Frontend

Build the Vue app with the API on the same domain and copy it to the folder Caddy serves:

```bash
VITE_API_BASE_URL=/api/ npm run build
sudo rsync -a --delete dist/ /srv/postgrade-frontend/
```

Same domain means `CORS_ALLOWED_ORIGINS` is not needed. If the frontend is ever hosted elsewhere, set `CORS_ALLOWED_ORIGINS` to its origin and build it with the API's full `https://` URL.

### 6.5 Start

```bash
docker compose up --build -d
docker compose run --rm web python manage.py check --deploy
docker compose run --rm web python manage.py createsuperuser
curl -fsS https://postgrade.example.com/health/ready/
```

Create lecturer accounts in Django admin (`/admin/`). Registration through the API is closed in production.

---

## 7. Operations

### 7.1 Health checks

| Endpoint | Meaning | Use for |
|---|---|---|
| `GET /health/live/` | The process is up. No database query. | Restart decisions (liveness). |
| `GET /health/ready/` | The process can reach the database (`SELECT 1`). `503` when it cannot. | Uptime monitoring, load balancer readiness. |

Both answer before host validation and HTTPS redirect, so probes using an IP address or plain HTTP work. They return only `{"status": ...}`. The compose file uses `/health/ready/` as the web container's health check.

Point a free external uptime monitor at `https://<domain>/health/ready/` so the team hears about an outage before the users do.

### 7.2 Logs

All containers log to stdout; Docker keeps the logs.

```bash
docker compose logs --since 1h web
docker compose logs -f recognition-worker mail-worker
```

- **Application logs** are JSON, one object per line (`time`, `level`, `logger`, `message`, `exception`).
- **Access logs** (gunicorn) record client, method, **path without the query string**, status, size and duration: `?search=` values can contain student names, so they are never logged.
- Log messages contain **IDs only** (submission, job, email), never names, student numbers, addresses or file contents. Tracebacks can contain server file paths, so treat logs as internal.
- Limit log size on the VM in `/etc/docker/daemon.json`: `{"log-driver": "local", "log-opts": {"max-size": "20m", "max-file": "5"}}`.

### 7.3 Job and email failures

| What | Where the lecturer sees it | Where an operator sees it |
|---|---|---|
| Recognition failed 3 times | Submission status `recognition_failed`; the submission's `recognition_job.failure_reason`; "retry recognition" action | `docker compose logs recognition-worker` ("Recognition job N failed on attempt M") |
| Recognition stuck | Submission stays `processing` > 5 min | Restart the worker; the job is recovered when its lease expires (`DOCS/RECOGNITION_WORKER.md`, 5.2) |
| Email not sent | `GET /api/assessments/{id}/script-emails/?status=failed`, with `failure_reason`; "retry" action | Django admin → *Script emails*, filter on status; `docker compose logs mail-worker` |
| Email provider down | Emails retry automatically, then show `failed` / `provider_error` | Same as above |

Details: `DOCS/RECOGNITION_WORKER.md` (Section 5) and `DOCS/SCRIPT_EMAIL_DELIVERY.md` (Sections 5 and 6).

### 7.4 Scaling

- **Recognition throughput:** ~1 script per minute per worker. For a batch upload, add a worker: `docker compose up -d --scale recognition-worker=2` (~0.7 GB more memory during recognition). Two workers also let one recover the other's jobs after a hang.
- **Web:** raise `WEB_CONCURRENCY` (about 2 per vCPU) before adding machines.
- **Database connections:** each web process and worker keeps one connection (`DB_CONN_MAX_AGE`). The default stack uses about 6 of PostgreSQL's 100.

---

## 8. Backups

The database and the media volume are the only state. Both must be backed up; one without the other leaves submissions pointing at missing files.

**Database:** follow `DOCS/BACKUP_RESTORE.md`. On the VM, run it nightly with cron:

```bash
0 2 * * * cd /opt/postgrade && docker compose exec -T db pg_dump -U postgrade -Fc postgrade > /var/backups/postgrade/db-$(date +\%F).dump
```

**Media:**

```bash
0 2 * * * docker run --rm -v postgrade_media:/data:ro -v /var/backups/postgrade:/backup alpine tar czf /backup/media-$(date +\%F).tgz -C /data .
```

Copy both files off the server (another region or the university's storage) and keep at least 14 days. Backups contain student data: store them encrypted and restrict access.

**Test a restore** before UAT and after any schema change (`DOCS/BACKUP_RESTORE.md`, *How to demonstrate recovery*).

---

## 9. Releasing and Rolling Back

### 9.1 Release

```bash
cd /opt/postgrade
git fetch && git checkout <release tag or commit>
# Backup first (Section 8) whenever the release contains migrations
docker compose build
docker compose up -d          # runs migrate, then restarts web and the workers
curl -fsS https://<domain>/health/ready/
```

Tag every release (`git tag v0.x.y`) so the previous version is always one checkout away. Running workers finish or abandon their current job when stopped; abandoned recognition jobs are recovered automatically (lease), and emails interrupted mid-send are marked `delivery_unknown` rather than sent twice.

### 9.2 Roll back

| Situation | Action |
|---|---|
| The release has **no migrations** | `git checkout <previous tag>`, `docker compose build`, `docker compose up -d`. |
| The release has migrations that **only add** (new tables/columns) | Same as above; the old code ignores the new columns. |
| The release has migrations that **change or remove** data | Restore the database backup taken before the release (Section 8), then deploy the previous tag. Data entered since the release is lost, so prefer a fix-forward when possible. |

Write migrations so they only add in one release and remove in a later one; then every rollback is the simple case.

---

## 10. Staging Acceptance Check

#14 requires a staging run of the whole workflow before production. Staging is a second deployment (Section 6) with its own domain, database and an SMTP **sandbox** account (e.g. a test inbox service) so no real student receives email.

| # | Step | Expected |
|---|---|---|
| 1 | `GET /health/ready/` | `200` |
| 2 | Log in as a lecturer created in admin | Dashboard loads |
| 3 | Create a course, import the class list CSV (synthetic students) | Students listed |
| 4 | Create an assessment and upload a synthetic script | Status `processing`, then `matched` or `needs_verification` within ~2 min |
| 5 | Open the submission; check the crop and the suggested student | Evidence shown |
| 6 | Verify the student and select Email script | Status `verified`; delivery queued or awaiting approval |
| 7 | Check the sandbox inbox | One script email for that student |
| 8 | Open the app on a nested URL directly (e.g. `/courses/1`) and refresh | Page loads (SPA fallback) |
| 9 | `check --deploy` | No warnings |

Record the date, the commit and the results on the #14 issue.

Use **synthetic** scripts and class lists only: invented names and student numbers on the real answer-sheet layout.

---

## 11. Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `ImproperlyConfigured: SECRET_KEY` at startup | Not set | Add it to `.env` (Section 6.2). |
| `400 Bad Request` for every request | Host not in `ALLOWED_HOSTS` | Add the domain; restart web. |
| Redirect loop between HTTP and HTTPS | The proxy does not send `X-Forwarded-Proto: https` | Use the Caddy configuration in 6.3. |
| Login always `429` for everyone | `NUM_PROXIES` is `0` behind the proxy, so all users share one limit | Set `NUM_PROXIES=1`. |
| Browser shows CORS errors | Frontend on another domain | Set `CORS_ALLOWED_ORIGINS` to the frontend origin, or serve both from one domain (6.4). |
| Admin pages unstyled | Static files are not served in production yet (Issue 01) | Functionality is unaffected. |
| Uploads stay `processing` | Recognition worker not running | `docker compose ps`; `docker compose up -d recognition-worker`. |
| Emails stay `queued` | Mail worker not running, or SMTP settings wrong | `docker compose logs mail-worker`. |
| `413 Request Entity Too Large` on upload | Proxy body limit below 15 MB | Raise `request_body max_size` (6.3). |
| `migrate` service exits non-zero | Migration error | `docker compose logs migrate`; restore from backup if data was changed. |

---

## 12. Issues List

| # | Issue | Status |
|---|---|---|
| 01 | Django admin's CSS/JS are not served in production (decision 26: WhiteNoise or the proxy). | On hold |
| 02 | The web container imports PaddleOCR in every gunicorn process (~96 MB and ~3.3 s each) although only the worker uses it. | Planned (separate PR) |
| 03 | Media lives on one machine's volume. Managed or multi-machine hosting needs a shared file share or object storage. | Open |
| 04 | The target environment (Section 3) needs team confirmation, and staging (Section 10) needs a hosting account and a sandbox email provider. | Open |
| 05 | No alerting beyond an external uptime monitor; failed jobs and emails are visible but not pushed to anyone. | Open |

## Script-only rollout

This release removes numeric grading. Before applying its migrations, stop writes/workers and back up the database/media; deploy the matching Vue version. See [MARKS_REMOVAL.md](MARKS_REMOVAL.md). Snapshot attachments require shared persistent private storage for web and mail workers.


## Account lifecycle rollout (#8)

Deploy the matching Vue auth PR before enabling backend refresh rotation. Run migrations (blacklist tables and shared throttle cache), then restart web workers. Existing password-unbound JWT sessions require a fresh sign-in. Lecturer signup is always available; the former ALLOW_REGISTRATION setting is no longer used. Read [PERMISSIONS.md](PERMISSIONS.md) for the endpoint matrix and proxy assumptions. Schedule `python manage.py flushexpiredtokens` daily. API throttle limits do not protect Django admin or guarantee strict limits under concurrency: configure perimeter rate limiting for auth and `/admin/login/`. Staff password resets invalidate old access/refresh sessions; role labels alone never grant staff or cross-owner API access.
