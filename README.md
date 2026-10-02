# PostGrade

PostGrade is a web application for managing and automating the grading workflow for assessments.

The project aims to streamline the processing of marked assessments, including student identification, grade management, and automated result distribution.

This repository contains the **Django REST API backend** for PostGrade.

## Tech Stack

- Python
- Django
- Django REST Framework
- PostgreSQL
- Simple JWT
- django-cors-headers

The PostGrade frontend is developed separately using Vue.js.

## Current Status

PostGrade is currently under active development.

### Phase 1 — Backend Foundation

The initial backend foundation includes:

- PostgreSQL database integration
- Environment-based configuration
- Custom email-based user model
- User roles:
  - Administrator
  - Lecturer
  - Marker
- User registration
- JWT authentication
- JWT token refresh
- Authenticated current-user endpoint
- Password validation
- CORS configuration for the Vue development server
- Automated tests for registration and authentication

### Features added since Phase 1

- Courses, owned by and visible only to the user who created them
- Students and enrollments, including CSV class-list import
- Assessments, results, a per-course gradebook and assessment statistics
- Submission upload with background student-number recognition (OCR), image quality checks and a manual verification queue
- Result email delivery through a background mail worker
- Continuous integration and database backup/restore documentation

Bubble-sheet recognition is planned but not yet implemented; only OCR-based recognition currently runs.

## Project Structure

```text
PostGradeDjango/
├── accounts/               # User accounts and authentication
├── assessments/            # Assessments, results, gradebook and statistics
├── config/                 # Django project configuration
├── courses/                # Courses (owned per user)
├── distribution/           # Result email delivery and mail worker
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
SECRET_KEY=your-django-secret-key
DEBUG=True

DB_NAME=postgrade
DB_USER=postgrade_user
DB_PASSWORD=your-database-password
DB_HOST=localhost
DB_PORT=5433
```

Never commit the `.env` file.

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
| `POST` | `/api/auth/register/` | Register a user |
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
python manage.py makemigrations --check
```
## Documentation

| Document | Covers |
|---|---|
| [`DOCS/API_REFERENCE.md`](DOCS/API_REFERENCE.md) | Endpoint inventory with request, response and error examples |
| [`DOCS/POSTGRESQL_SETUP.md`](DOCS/POSTGRESQL_SETUP.md) | Local database setup |
| [`DOCS/RECOGNITION_EVIDENCE_API.md`](DOCS/RECOGNITION_EVIDENCE_API.md) | Submission and recognition API, quality checks |
| [`DOCS/RECOGNITION_WORKER.md`](DOCS/RECOGNITION_WORKER.md) | Recognition worker setup and troubleshooting |
| [`DOCS/RESULT_EMAIL_DELIVERY.md`](DOCS/RESULT_EMAIL_DELIVERY.md) | Result email delivery |
| [`DOCS/BACKUP_RESTORE.md`](DOCS/BACKUP_RESTORE.md) | Database backup and recovery |
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