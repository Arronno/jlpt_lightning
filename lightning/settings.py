import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get(
        "JLPT_DATA_DIR",
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "JLPTLightning",
    )
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_FILE = DATA_DIR / "secret.key"
if not SECRET_FILE.exists():
    import secrets

    try:
        with SECRET_FILE.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(64))
    except FileExistsError:
        pass
SECRET_KEY = SECRET_FILE.read_text(encoding="utf-8")
DEBUG = os.environ.get("JLPT_DEBUG") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "testserver"]
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "learning.apps.LearningConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "learning.middleware.PrivateResponses",
]
ROOT_URLCONF = "lightning.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "learning.context.preferences",
            ]
        },
    }
]
WSGI_APPLICATION = "lightning.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "learning.sqlite3",
        "OPTIONS": {
            "timeout": 5,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;",
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "Asia/Tokyo"
USE_TZ = True
LANGUAGE_CODE = "en"
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = DEBUG
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "catalog",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 100},
    }
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(DATA_DIR / "app.log"),
            "maxBytes": 1_000_000,
            "backupCount": 3,
            "formatter": "plain",
        }
    },
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "root": {"handlers": ["file"], "level": "INFO"},
}
