"""
TIXSYS settings.

Everything that changes between servers comes from environment variables,
which Docker Compose reads from the .env file. See .env.example.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    value = os.environ.get(name)
    return default if value in (None, "") else value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    value = os.environ.get(name)
    return default if value in (None, "") else int(value)


DEBUG = env_bool("DEBUG", False)

SECRET_KEY = env("SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY is not set. Run ./tixsys setup to create the .env file.")

# --- Address -----------------------------------------------------------------
# TIXSYS_DOMAIN is the address people type, e.g. help.example.org.
# For a quick test without a domain, use http://<server-ip> (no HTTPS).
_raw_domain = env("TIXSYS_DOMAIN", "localhost").strip().rstrip("/")
HTTP_ONLY = _raw_domain.startswith("http://")
SITE_HOST = _raw_domain.split("://", 1)[-1]
SITE_URL = ("http://" if HTTP_ONLY else "https://") + SITE_HOST

_host_only = SITE_HOST.split(":")[0]
ALLOWED_HOSTS = [_host_only, "localhost", "127.0.0.1"] + [
    h.strip() for h in env("EXTRA_ALLOWED_HOSTS", "").split(",") if h.strip()
]
CSRF_TRUSTED_ORIGINS = [SITE_URL] + [
    o.strip() for o in env("EXTRA_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# --- Apps --------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "helpdesk",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "helpdesk.middleware.CurrentOrganizationMiddleware",
    "helpdesk.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "helpdesk.context.site",
            ],
        },
    },
]

# --- Database ----------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "tixsys"),
        "USER": env("POSTGRES_USER", "tixsys"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The cache lives in the database, so all app workers share the
# sign-in lockout and rate-limit counters. No extra service needed.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "tixsys_cache",
    }
}

# --- Accounts and sign-in ----------------------------------------------------
AUTH_USER_MODEL = "helpdesk.User"
LOGIN_URL = "/staff/login/"
LOGIN_REDIRECT_URL = "/staff/"
LOGOUT_REDIRECT_URL = "/staff/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_AGE = 60 * 60 * 10  # staff stay signed in for 10 hours
SESSION_COOKIE_NAME = "tixsys_session"

# Failed sign-ins: after LOGIN_SLOWDOWN_AFTER failures a wait is enforced;
# after LOGIN_LOCKOUT_AFTER failures the account is locked for LOGIN_LOCKOUT_MINUTES.
LOGIN_SLOWDOWN_AFTER = env_int("LOGIN_SLOWDOWN_AFTER", 5)
LOGIN_LOCKOUT_AFTER = env_int("LOGIN_LOCKOUT_AFTER", 10)
LOGIN_LOCKOUT_MINUTES = env_int("LOGIN_LOCKOUT_MINUTES", 30)
LOGIN_IP_LOCKOUT_AFTER = env_int("LOGIN_IP_LOCKOUT_AFTER", 30)

# --- Public portal limits ----------------------------------------------------
PORTAL_TICKETS_PER_IP_PER_HOUR = env_int("PORTAL_TICKETS_PER_IP_PER_HOUR", 40)
PORTAL_TICKETS_PER_EMAIL_PER_HOUR = env_int("PORTAL_TICKETS_PER_EMAIL_PER_HOUR", 10)
PORTAL_REPLIES_PER_IP_PER_HOUR = env_int("PORTAL_REPLIES_PER_IP_PER_HOUR", 120)
PORTAL_MIN_FORM_SECONDS = env_int("PORTAL_MIN_FORM_SECONDS", 3)

# --- Attachments -------------------------------------------------------------
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
MAX_ATTACHMENT_MB = env_int("MAX_ATTACHMENT_MB", 10)
MAX_ATTACHMENTS_PER_UPLOAD = env_int("MAX_ATTACHMENTS_PER_UPLOAD", 5)
DATA_UPLOAD_MAX_NUMBER_FILES = MAX_ATTACHMENTS_PER_UPLOAD + 1
FILE_UPLOAD_PERMISSIONS = 0o640

# --- Email (optional) --------------------------------------------------------
# Email is turned on by setting EMAIL_HOST in .env. When it's off, nothing is sent.
EMAIL_ENABLED = bool(env("EMAIL_HOST"))
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = env("EMAIL_FROM", EMAIL_HOST_USER or "helpdesk@localhost")
if not EMAIL_ENABLED:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# --- Language and time -------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "America/Los_Angeles")
USE_I18N = False
USE_TZ = True

# --- Static files ------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --- HTTPS and browser protections -------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
COOKIES_SECURE = not DEBUG and not HTTP_ONLY
SESSION_COOKIE_SECURE = COOKIES_SECURE
CSRF_COOKIE_SECURE = COOKIES_SECURE
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 0 if (DEBUG or HTTP_ONLY) else env_int("HSTS_SECONDS", 60 * 60 * 24 * 30)
SECURE_CONTENT_TYPE_NOSNIFF = True
# Private ticket links must never leak to other sites through the Referer header.
# ("no-referrer" would also break form posts: browsers then send Origin: null.)
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# The proxy (Caddy) puts the visitor's real address in X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # 403s and 404s are normal on a public site; only log real errors.
        "django.request": {"level": "ERROR"},
        # Bots scanning the server's IP address trigger these constantly.
        "django.security.DisallowedHost": {"handlers": [], "propagate": False},
    },
}
