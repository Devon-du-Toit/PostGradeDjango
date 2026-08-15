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

## Project Structure

```text
PostGradeDjango/
├── accounts/               # User accounts and authentication
├── config/                 # Django project configuration
├── DOCS/                   # Project documentation
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

The Vue.js frontend is maintained separately in the `PostGradeVue` repository.

## License

A license has not yet been specified.