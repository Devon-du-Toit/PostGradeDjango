import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


def env_list(name, default=""):
    # Comma-separated environment value, e.g. "a.example.com,b.example.com".
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


# Every value below comes from the environment; the defaults are the local
# development values, so production differences live only in its environment.
# See DOCS/DEPLOYMENT.md and https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Set the SECRET_KEY environment variable (see .env.example)."
    )

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DEBUG")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # PostGrade apps
    "accounts",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "courses",
    "students",
    "assessments",
    "submissions",
    "distribution",
    "dashboard",
]

MIDDLEWARE = [
    # First, so probes skip host validation, redirects and authentication.
    "config.health.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT"),
        # Seconds to reuse a connection across requests (0 = new connection
        # per request, the development default). Production: 60.
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "0")),
        "CONN_HEALTH_CHECKS": True,
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "accounts.password_validation.SpecialCharacterValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target (Django admin assets)


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

# Console by default (development); production sets the SMTP backend and host.
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "PostGrade <noreply@postgrade.local>",
)

# Seconds before an SMTP connection gives up, so a stalled mail server
# cannot block the mail worker.
EMAIL_TIMEOUT = 30

# "automatic": an explicit email-script request queues delivery.
# "approval": requested script emails wait for lecturer approval.
SCRIPT_EMAIL_RELEASE_POLICY = os.getenv(
    "SCRIPT_EMAIL_RELEASE_POLICY",
    "automatic",
)

AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PAGINATION_CLASS": "config.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ),
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# Origins allowed to submit forms with a CSRF token over HTTPS (Django admin).
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))


# HTTPS
# The app runs behind the hosting platform's HTTPS proxy, which forwards
# plain HTTP and says which scheme the client used.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Opt-in, so tests, local runs and internal probes are never redirected.
# Production: SECURE_SSL_REDIRECT=true, and SECURE_HSTS_SECONDS=31536000
# once HTTPS is confirmed working (browsers then refuse plain HTTP).
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT")
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))

# HSTS for subdomains/preload is deliberately off: on a subdomain of a shared
# (e.g. university) domain it would force HTTPS on every other site under it.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]


# Logging
# Everything goes to stdout, where the hosting platform collects it. JSON in
# production (one searchable object per line), readable text in development.
# Log IDs, never names, student numbers, email addresses or file contents.

LOG_FORMAT = os.getenv("LOG_FORMAT", "text" if DEBUG else "json")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "config.log_format.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
}


# Submission file validation limits.
# A submission is one student's whole script (returned to the
# student), so several pages are allowed; recognition reads page 1.
# These are not general-purpose document storage limits.
MAX_SUBMISSION_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_SUBMISSION_PDF_PAGES = 20
MAX_SUBMISSION_IMAGE_DIMENSION_PX = 6000

# Export is built on temporary disk before sending headers; bounds cover raw bytes.
MAX_SCRIPT_EXPORT_FILES = int(os.getenv("MAX_SCRIPT_EXPORT_FILES", "1000"))
MAX_SCRIPT_EXPORT_BYTES = int(
    os.getenv("MAX_SCRIPT_EXPORT_BYTES", str(512 * 1024 * 1024))
)


# Class-list CSV import (students/csv_import.py).
MAX_CSV_IMPORT_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_CSV_IMPORT_ROWS = 5000

# Bubble matching is exact and requires eight unambiguous columns.
BUBBLE_AUTO_MATCH_ENABLED = (
    os.getenv("BUBBLE_AUTO_MATCH_ENABLED", "True").lower() == "true"
)


# Public lecturer signup is always available.
ALLOW_PASSWORD_RECOVERY = env_bool("ALLOW_PASSWORD_RECOVERY", DEBUG)
PASSWORD_RESET_FRONTEND_URL = os.getenv(
    "PASSWORD_RESET_FRONTEND_URL",
    "http://localhost:5173/reset-password" if DEBUG else "",
)
PASSWORD_RESET_TIMEOUT = 3600
EMAIL_TIMEOUT = 10
PASSWORD_RESET_THROTTLE_RATE = os.getenv("PASSWORD_RESET_THROTTLE_RATE", "5/hour")
PASSWORD_RESET_CONFIRM_THROTTLE_RATE = os.getenv(
    "PASSWORD_RESET_CONFIRM_THROTTLE_RATE", "10/hour"
)
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "throttle": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "auth_throttle_cache",
    },
}
LOGIN_THROTTLE_RATE = os.getenv("LOGIN_THROTTLE_RATE", "10/min")
REGISTER_THROTTLE_RATE = os.getenv("REGISTER_THROTTLE_RATE", "5/hour")
REFRESH_THROTTLE_RATE = os.getenv("REFRESH_THROTTLE_RATE", "30/min")
LOGOUT_THROTTLE_RATE = os.getenv("LOGOUT_THROTTLE_RATE", "30/min")
REST_FRAMEWORK["NUM_PROXIES"] = int(os.getenv("NUM_PROXIES", "0"))
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "CHECK_REVOKE_TOKEN": True,
}

# Includes excluded duplicates, bounding cumulative group rebuild cost.
MAX_QR_GROUP_PAGES = int(os.getenv("MAX_QR_GROUP_PAGES", "100"))
MAX_QR_GROUP_BYTES = int(os.getenv("MAX_QR_GROUP_BYTES", str(15 * 1024 * 1024)))
