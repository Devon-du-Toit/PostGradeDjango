# PostGrade

PostGrade identifies student numbers in uploaded scripts, supports lecturer verification, and returns verified files by tracked email delivery. No numeric marks or grades are entered or calculated.

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

The backend provides owner-scoped courses, students/enrollments, validated CSV imports, assessments, paginated search/filtering and dashboard counts. Uploads validate PDF/image content and queue OCR or filled-bubble recognition. Lecturers verify the enrolled student, then explicitly request email delivery of that script. The mail worker attaches a stored copy of the verified file. Approval, retry and delivery history remain available.

Course/assessment archives preserve files/audits and stop queued work. QR multipage grouping and ZIP export remain unavailable. See [MARKS_REMOVAL.md](DOCS/MARKS_REMOVAL.md) for the coordinated backend/frontend rollout and the migration that removes stored numeric results.

## Project Structure

```text
PostGradeDjango/
├── accounts/               # User accounts and authentication
├── assessments/            # Assessments and archive lifecycle
├── config/                 # Django project configuration
├── courses/                # Courses (owned per user)
├── distribution/           # Verified script email delivery and mail worker
├── dashboard/              # Owner-scoped counts and assessment progress
├── students/               # Students, enrollments and CSV class-list import
├── submissions/            # Submission upload, recognition, verification and protected files
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

Requested script emails are sent by a background worker. In a separate terminal, with the same virtual environment active:

```bash
python manage.py run_mail_worker
```

Without a mail worker, verification still succeeds but requested script emails remain queued. See [`DOCS/SCRIPT_EMAIL_DELIVERY.md`](DOCS/SCRIPT_EMAIL_DELIVERY.md) for details.

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
The full endpoint inventory, with request, response and error examples, is in [`DOCS/API_REFERENCE.md`](DOCS/API_REFERENCE.md). Submission and recognition endpoints are covered in [`DOCS/RECOGNITION_EVIDENCE_API.md`](DOCS/RECOGNITION_EVIDENCE_API.md), and script emails in [`DOCS/SCRIPT_EMAIL_DELIVERY.md`](DOCS/SCRIPT_EMAIL_DELIVERY.md).

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
| [`DOCS/SCRIPT_EMAIL_DELIVERY.md`](DOCS/SCRIPT_EMAIL_DELIVERY.md) | Verified script email delivery |
| [`DOCS/BACKUP_RESTORE.md`](DOCS/BACKUP_RESTORE.md) | Database backup and recovery |
| [`DOCS/API_CONTRACT.md`](DOCS/API_CONTRACT.md) | Pagination, filters, types and dashboard semantics |
| [`DOCS/PERMISSIONS.md`](DOCS/PERMISSIONS.md) | Release auth matrix, signup/throttling and account follow-ups |
| [`DOCS/ARCHIVING.md`](DOCS/ARCHIVING.md) | Release archive policy, retained files and worker behavior |
| [`DOCS/DEPLOYMENT.md`](DOCS/DEPLOYMENT.md) | Containers, HTTPS/proxy/CORS, workers, staging and rollback |
| [`DOCS/CI.md`](DOCS/CI.md), [`DOCS/DB_REVIEW.md`](DOCS/DB_REVIEW.md) | CI pipeline and database review notes |

## Development Roadmap

PostGrade is being developed incrementally.

- **Phase 1:** Backend foundation and authentication
- **Phase 2:** Course, student and assessment domain APIs
- **Phase 3:** Assessment and document processing
- **Phase 4:** Automated student identification
- **Phase 5:** Verified script distribution and workflow automation
- **Phase 6:** Production readiness and deployment

The roadmap will evolve as the system develops.

## Related Repository

The Vue.js frontend is maintained separately in the [PostGradeVue](https://github.com/Devon-du-Toit/PostGradeVue) repository.

## License

A license has not yet been specified.

Bubble recognition and method selection: [guide](DOCS/BUBBLE_RECOGNITION.md). After updating, run migrations before starting web/recognition workers.
