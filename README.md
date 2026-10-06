# PostGrade

PostGrade helps identify, verify and distribute already-marked assessments,
with grade management and result notification for lecturers.

The project aims to streamline the processing of marked assessments, including student identification, grade management, and automated result distribution.

This repository contains the **Django REST API backend** for PostGrade.

## Tech Stack

- Python 3.12 (CI/container runtime)
- Django
- Django REST Framework
- PostgreSQL
- Simple JWT
- django-cors-headers and django-filter
- PaddleOCR/PaddlePaddle, OpenCV, Pillow and PyMuPDF

The PostGrade frontend is developed separately using Vue.js.

## Current Status

The backend provides owner-scoped courses, students/enrollments, validated
CSV imports with dry runs and explicit updates, assessments/results,
gradebooks/statistics, paginated filters/search and dashboard summaries.
Uploads validate PDF/image content and return immediately while a separate
OCR worker processes them. Lecturers verify the identity before marking;
result-text emails are recorded with the mark and sent by a mail worker.
Originals and recognition crops are retrieved through authenticated APIs.

Course/assessment archiving is merged, preserving historical records/files
and blocking archived workflows. **Merge prerequisites still apply** to
production signup/throttling, failed recognitions in the review queue and
Ruff lint: those changes were merged into stacked branches rather than
master. See the
[release integration status](DOCS/API_REFERENCE.md#14-release-integration-status)
before treating those release rules as deployed behavior. This PR changes
documentation only; it does not integrate the pending implementation code.

Bubble recognition and QR multipage grouping remain planned. Result emails
currently contain marks/percentages, without script attachments or student
download access. Production hosting and a successful staging demonstration
are still required; a container/runbook does not establish deployment.

## Project Structure

```text
PostGradeDjango/
├── accounts/               # User accounts and authentication
├── assessments/            # Assessments, results, gradebook and statistics
├── config/                 # Django project configuration
├── courses/                # Courses (owned per user)
├── distribution/           # Result email delivery and mail worker
├── dashboard/              # Owner-scoped counts and assessment progress
├── students/               # Students, enrollments and CSV class-list import
├── submissions/            # Submission upload, recognition, verification and marking
├── DOCS/                   # Project documentation
├── .github/                # CI workflow
├── .env.example            # Example environment configuration
├── .gitignore
├── manage.py
├── README.md
└── requirements.txt
```

## Local Development

### 1. Clone the repository

```bash
git clone git@github.com:Devon-du-Toit/PostGradeDjango.git
cd PostGradeDjango
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure PostgreSQL

PostGrade uses PostgreSQL as its database backend.

Detailed setup instructions are available in:

```text
DOCS/POSTGRESQL_SETUP.md
```

### 5. Configure environment variables

Copy `.env.example` to `.env` and provide your local configuration.

Example:

```env
SECRET_KEY=replace-with-a-generated-secret-key
DEBUG=True

DB_NAME=postgrade
DB_USER=postgrade_user
DB_PASSWORD=your-database-password
DB_HOST=localhost
DB_PORT=5433
```

Generate the secret after installing dependencies:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Use your actual PostgreSQL port (the example uses 5433). Local defaults
permit `localhost`/`127.0.0.1` and the Vue origin `http://localhost:5173`.
For production set `DEBUG=False`, allowed hosts, HTTPS/CORS, private media
and SMTP as described in [DEPLOYMENT.md](DOCS/DEPLOYMENT.md). After auth
hardening is integrated, `ALLOW_REGISTRATION` defaults to `DEBUG`; closed
signup requires administrator-created accounts. Configure `NUM_PROXIES`
for the trusted hosting proxy. Never commit `.env` or use example secrets.


### 6. Apply migrations

```bash
python manage.py migrate
```

### 7. Run the development server

```bash
python manage.py runserver
```

The Django development server will normally be available at:

```text
http://127.0.0.1:8000/
```

### 8. Run the recognition worker

Student-number recognition runs in a background worker. In a second terminal, with the same virtual environment active:

```bash
python manage.py run_recognition_worker
```

Without a running worker, uploaded submissions remain in the `processing` state. See [`DOCS/RECOGNITION_WORKER.md`](DOCS/RECOGNITION_WORKER.md) for details.

### 9. Run the mail worker

Result emails are sent by a background worker. In a separate terminal, with the same virtual environment active:

```bash
python manage.py run_mail_worker
```

Without a running mail worker, marks are saved normally but result emails remain queued. See [`DOCS/RESULT_EMAIL_DELIVERY.md`](DOCS/RESULT_EMAIL_DELIVERY.md) for details.

## API

Authentication endpoints are available under `/api/auth/`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register/` | Register when enabled; release policy disables production signup by default |
| `POST` | `/api/auth/login/` | Obtain JWT access and refresh tokens |
| `POST` | `/api/auth/refresh/` | Obtain a new access token |
| `GET` | `/api/auth/me/` | Get the authenticated user's details |

Protected endpoints use JWT Bearer authentication:

```http
Authorization: Bearer <access_token>
```
The full endpoint inventory, with request, response and error examples, is in [`DOCS/API_REFERENCE.md`](DOCS/API_REFERENCE.md). Submission and recognition endpoints are covered in [`DOCS/RECOGNITION_EVIDENCE_API.md`](DOCS/RECOGNITION_EVIDENCE_API.md), and result emails in [`DOCS/RESULT_EMAIL_DELIVERY.md`](DOCS/RESULT_EMAIL_DELIVERY.md).

## Running Tests

Run the complete Django test suite with:

```bash
python manage.py test
```

Additional project checks can be run with:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```
The full suite includes real OCR tests and needs the pinned runtime and
model files. CI runs audit/email/submission/verification tests first, then
the whole suite. See [CI.md](DOCS/CI.md). Once the stacked cleanup tooling
is integrated, run its check-only commands:

```bash
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
```

Ruff lint is enforced; formatting is temporarily non-blocking until the
separate formatting pass. These commands require the cleanup branch's
`requirements-dev.txt`/`pyproject.toml`; they are not present on the inspected
master yet.

## Documentation

| Document | Covers |
|---|---|
| [`DOCS/API_REFERENCE.md`](DOCS/API_REFERENCE.md) | Endpoint inventory with request, response and error examples |
| [`DOCS/POSTGRESQL_SETUP.md`](DOCS/POSTGRESQL_SETUP.md) | Local database setup |
| [`DOCS/RECOGNITION_EVIDENCE_API.md`](DOCS/RECOGNITION_EVIDENCE_API.md) | Submission and recognition API, quality checks |
| [`DOCS/RECOGNITION_WORKER.md`](DOCS/RECOGNITION_WORKER.md) | Recognition worker setup and troubleshooting |
| [`DOCS/RESULT_EMAIL_DELIVERY.md`](DOCS/RESULT_EMAIL_DELIVERY.md) | Result email delivery |
| [`DOCS/BACKUP_RESTORE.md`](DOCS/BACKUP_RESTORE.md) | Database backup and recovery |
| [`DOCS/API_CONTRACT.md`](DOCS/API_CONTRACT.md) | Pagination, filters, types and dashboard semantics |
| [`DOCS/PERMISSIONS.md`](DOCS/PERMISSIONS.md) | Release auth matrix, signup/throttling and account follow-ups |
| [`DOCS/ARCHIVING.md`](DOCS/ARCHIVING.md) | Release archive policy, retained files and worker behavior |
| [`DOCS/DEPLOYMENT.md`](DOCS/DEPLOYMENT.md) | Containers, HTTPS/proxy/CORS, workers, staging and rollback |
| [`DOCS/CI.md`](DOCS/CI.md), [`DOCS/DB_REVIEW.md`](DOCS/DB_REVIEW.md) | CI pipeline and database review notes |

## Development Roadmap

PostGrade is being developed incrementally.

- **Phase 1:** Backend foundation and authentication
- **Phase 2:** Core grading domain models and APIs
- **Phase 3:** Assessment and document processing
- **Phase 4:** Automated student identification
- **Phase 5:** Result distribution and workflow automation
- **Phase 6:** Production readiness and deployment

The roadmap will evolve as the system develops.

## Related Repository

The Vue.js frontend is maintained separately in the [PostGradeVue](https://github.com/Devon-du-Toit/PostGradeVue) repository.

## License

A license has not yet been specified.

Bubble recognition and method selection: [guide](DOCS/BUBBLE_RECOGNITION.md). After updating, run migrations before starting web/recognition workers.
