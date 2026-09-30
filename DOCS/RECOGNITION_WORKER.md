# Recognition Worker

PostGrade — Group 13

Version 0.1.0

## Revision History

| Date | Version | Description | Author |
|---|---|---|---|
| 24/09/2026 | 0.1.0 | Background recognition worker: design, local setup and operation (Issue #5). | Graham Robert |

## Table of Contents

1. [Introduction](#1-introduction)
2. [How It Works](#2-how-it-works)
3. [Local Setup](#3-local-setup)
4. [Command Reference](#4-command-reference)
5. [Reliability Behaviour](#5-reliability-behaviour)
6. [Configuration](#6-configuration)
7. [Production Notes](#7-production-notes)
8. [Troubleshooting](#8-troubleshooting)
9. [Issues List](#9-issues-list)

---

## 1. Introduction

### 1.1 Purpose

This document describes the recognition worker: the background process that performs student-number recognition on uploaded scripts. It explains how the worker fits into the upload workflow, how to run it during local development, and how it behaves when recognition or the worker itself fails.

### 1.2 Background

Recognition previously ran inside the upload request, so a lecturer's upload did not complete until OCR had finished. Recognition now runs in a separate worker process. An upload is stored and returned immediately with the status `processing`, and the worker updates the submission when recognition completes.

### 1.3 Requirement Traceability

| Requirement | Source | Addressed by |
|---|---|---|
| Uploaded scripts move from storage into background processing | Technical Specification, Component Interaction | Sections 2, 3 |
| SF4-FR7 / SF5-FR9 Isolate individual file failures | Technical Specification | Section 5.1 |
| SF8-FR4 Script lifecycle state machine | Technical Specification | Section 2.3 |
| Performance: Fault Isolation, Retry Process, Processing Status | Technical Specification | Sections 5.1–5.3 |
| Script-Processing State-Transition Diagram (Failed state, lecturer retry) | Functional Specification, Analysis Models | Sections 2.3, 5.3 |

---

## 2. How It Works

### 2.1 Components

| Component | Where it runs | Responsibility |
|---|---|---|
| Web server | `python manage.py runserver` (development) | Stores the upload and adds a job to the queue. Returns immediately. |
| Job queue | `submissions_recognitionjob` table in PostgreSQL | Holds one row per recognition request. Rows with status `queued` are waiting to run. |
| Worker | `python manage.py run_recognition_worker` | Claims queued jobs, runs recognition and records the result. |

No additional infrastructure (such as Redis) is required. The queue is a table in the existing database.

### 2.2 Flow

```
Vue ──POST /api/submissions/──▶ web server
                                  1. save submission (status: processing)
                                  2. create job (status: queued)      ─┐ one transaction
                                ◀── 201 Created (immediately)          ─┘
                                        │
                                  job queue (PostgreSQL)
                                        │
                                  worker: claim job → run recognition → save result
                                        │
Vue ──GET /api/submissions/{id}/──▶ status: matched / needs_verification / recognition_failed
```

The submission and its job are created in the same database transaction. The worker cannot see a job until the upload has committed, and a failed upload leaves no job behind.

### 2.3 Submission and Job States

A submission's `status` reflects its place in the review workflow; a job's `status` reflects one recognition request.

```
Submission:  processing ──▶ matched ─────────────┐
                 │     ──▶ needs_verification ───┼──▶ verified ──▶ marked
                 │                               │
                 └────▶ recognition_failed ──(lecturer retry)──▶ processing

Job:  queued ──claim──▶ running ──▶ succeeded
        ▲                  │
        └── error, retries ├──▶ failed      (retries exhausted)
            remaining      └──▶ cancelled   (file replaced)
```

---

## 3. Local Setup

### 3.1 Prerequisites

- The backend is set up as described in `README.md` and `DOCS/POSTGRESQL_SETUP.md`.
- Migrations are applied:

  ```bash
  python manage.py migrate
  ```

### 3.2 Running the Worker

The worker runs **alongside** the development server, in a second terminal. Both use the same virtual environment and `.env`.

Terminal 1 — web server:

```bash
python manage.py runserver
```

Terminal 2 — recognition worker:

```bash
python manage.py run_recognition_worker
```

Expected output:

```
Recognition worker started.
```

The first job processed after the worker starts takes longer than the rest, because PaddleOCR loads its models into memory on first use.

### 3.3 Stopping the Worker

Press `Ctrl+C`. The worker finishes the job it is currently processing, then exits:

```
Recognition worker stopped.
```

If the worker is stopped abruptly (terminal closed, process killed), the job it was processing is recovered automatically by the next worker to start (Section 5.2).

### 3.4 Without a Worker

If no worker is running, uploads succeed but remain in `processing`. Queued jobs are not lost: they are processed as soon as a worker starts.

---

## 4. Command Reference

```bash
python manage.py run_recognition_worker [--poll-interval SECONDS] [--once]
```

| Option | Default | Description |
|---|---|---|
| `--poll-interval` | `2.0` | Seconds to wait before checking the queue again when it is empty. |
| `--once` | off | Process all jobs that are currently due, then exit. Useful for testing and scheduled runs. |

Several workers may run at the same time. Each job is claimed by exactly one worker.

---

## 5. Reliability Behaviour

### 5.1 Recognition Errors

If recognition raises an error, the job is retried after a delay:

| Attempt | On failure |
|---|---|
| 1 | Retried after 30 seconds |
| 2 | Retried after 2 minutes |
| 3 | Job `failed`; submission `recognition_failed` |

A failure affects only that script. Other scripts in the batch continue to be processed.

The lecturer sees the job's progress in the submission's `recognition_job` field, including `attempts` and a `failure_reason` containing the error type only (for example `RuntimeError`). The full error text is kept in the database and the worker log, because it can contain server file paths.

### 5.2 Worker Crashes and Timeouts

When a worker claims a job, it takes a **lease** of 5 minutes. If the lease expires before the job finishes, the worker is presumed to have crashed or hung, and the job is recovered:

- Attempts remaining → the job is re-queued and runs again immediately.
- No attempts remaining → the job is `failed` and the submission `recognition_failed`.

Every worker checks for expired leases when it starts and every 60 seconds afterwards. A crash counts as an attempt, so a script that crashes the worker every time fails after three attempts instead of crashing workers indefinitely.

### 5.3 Lecturer Retry

A lecturer can re-run recognition on a submission with status `recognition_failed` or `needs_verification`:

```
POST /api/submissions/{id}/retry-recognition/
```

A new job is created with a fresh set of attempts. Repeated retry requests while the job is pending have no further effect. See `DOCS/RECOGNITION_EVIDENCE_API.md`, Section 6.5.

### 5.4 Duplicate and Stale Jobs

| Situation | Behaviour |
|---|---|
| The same submission is queued twice | Only one active job can exist per submission (database constraint). The second request returns the existing job. |
| Two workers check the queue at the same moment | Each job is claimed by exactly one worker (`SELECT … FOR UPDATE SKIP LOCKED`). |
| A slow worker finishes after its job was recovered and re-run | Its result is discarded. Each claim carries an attempt number, and only the worker holding the current attempt may save a result. |
| The lecturer verifies a submission while its job is running | The job's result is discarded. Results are only saved to submissions still in `processing`. |
| The file is replaced while its job is running | The old job is `cancelled` and its result is discarded. A new job is queued for the new file. |

---

## 6. Configuration

These values are defined in code. Changing them requires a code change and, for `max_attempts`, applies only to jobs created afterwards.

| Setting | Value | Location |
|---|---|---|
| Maximum attempts per job | 3 | `RecognitionJob.max_attempts` default, `submissions/models.py` |
| Retry delays | 30 s, 2 min | `RETRY_DELAYS`, `submissions/jobs.py` |
| Lease duration | 5 min | `LEASE_DURATION`, `submissions/jobs.py` |
| Lease recovery interval | 60 s | `RECOVERY_INTERVAL`, `submissions/management/commands/run_recognition_worker.py` |
| Queue poll interval | 2 s | `--poll-interval` option |

The retry limit is listed as TBD in the Technical Specification Issues List (Issue 05); three attempts is the current working value.

---

## 7. Production Notes

- The worker must run as a **managed service** that starts on boot and restarts on exit (for example a Docker container with a restart policy, a systemd unit, or a Windows service). It must not be run from an interactive terminal.
- The worker needs the same code, environment variables and database access as the web server, and read access to the uploaded files (`MEDIA_ROOT`).
- Run **at least two** workers so that one can recover jobs from another that has hung (see Issue 01).
- Each worker loads its own copy of the PaddleOCR models, which uses several hundred megabytes of memory. Size the host accordingly.
- Worker errors are currently written to the worker's console only. Production logging is part of Issue #14.

---

## 8. Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| Uploads stay in `processing` | No worker is running | Start `run_recognition_worker`. |
| `processing` for several minutes, then processed | A worker crashed; its job waited for the 5-minute lease to expire | None required. Check the worker log for the cause. |
| Submissions end in `recognition_failed` | Recognition raised an error three times | Check `recognition_job.failure_reason` and the worker log, fix the cause, then use the retry action. |
| `You have unapplied migration(s)` on startup | Migrations `0004`/`0005` not applied | Run `python manage.py migrate`. |
| Worker stops processing but is still running | Recognition is hung inside that worker | Restart the worker. Its job is recovered after the lease expires. |

---

## 9. Issues List

| ID | Description | Status |
|---|---|---|
| 01 | A worker that **hangs** (rather than crashes) cannot recover its own job, and stays blocked. With a single worker, nothing is processed until it is restarted. A hard per-job timeout requires running recognition in a separate, killable process. | TBD |
| 02 | Errors that will always recur (for example a corrupt file) are still retried three times before failing. Classifying permanent errors would fail these immediately. | TBD |
| 03 | The worker polls the database every 2 seconds when idle. PostgreSQL `LISTEN/NOTIFY` would start jobs without delay. | TBD |
| 04 | The retry limit and delays are fixed in code. They depend on Technical Specification Issue 05. | TBD |
