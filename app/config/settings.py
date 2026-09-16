"""Application-only settings; no SSH or AI credentials are loaded by the web process."""

import os
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Containers never contain this ignored local file. Existing environment wins.
load_dotenv(BASE_DIR.parent / ".env.app", override=False)
APP_ENV = os.environ.get("APP_ENV", "local")
if APP_ENV not in {"local", "test", "build", "production"}:
    raise ImproperlyConfigured("Unknown APP_ENV")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required setting is missing: {name}")
    return value


def boolean(name: str, default: str = "false") -> bool:
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false"}:
        raise ImproperlyConfigured(f"{name} must be true or false")
    return value == "true"


SECRET_KEY = required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must contain at least 50 characters")
DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in required("DJANGO_ALLOWED_HOSTS").split(",")]
if any(not host or host == "*" for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Explicit DJANGO_ALLOWED_HOSTS are required")
version_file = BASE_DIR / "build-version.txt"
APP_VERSION = (
    version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "local"
)
if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", APP_VERSION):
    raise ImproperlyConfigured("Invalid APP_VERSION")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "catalog",
    "processing",
    "reviews",
    "summaries",
    "presentation",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required("POSTGRES_DB"),
        "USER": required("DATABASE_USER")
        if "DATABASE_USER" in os.environ
        else required("WEB_DB_USER"),
        "PASSWORD": (
            required("DATABASE_PASSWORD")
            if "DATABASE_PASSWORD" in os.environ
            else required("WEB_DB_PASSWORD")
        ),
        "HOST": required("POSTGRES_HOST"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
OPS_MONITORING_ENABLED = boolean("OPS_MONITORING_ENABLED", "true")
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Early IMP-01 is read-only HTTP. TLS is mandatory before G6, not claimed here.
SECURE_SSL_REDIRECT = boolean("DJANGO_HTTPS")
SECURE_HSTS_SECONDS = 31536000 if SECURE_SSL_REDIRECT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
SECURE_HSTS_PRELOAD = False
# Only Caddy reaches web in the deployment network and overwrites this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REDIRECT_EXEMPT = [r"^health/live/$", r"^health/ready/$"]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"safe": {"()": "config.safe_logging.SafeFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "safe"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.server": {"handlers": ["console"], "propagate": False}},
}
