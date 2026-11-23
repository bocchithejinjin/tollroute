import os

import dj_database_url


from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_key() -> str:
    """SECRET_KEY: 環境変数 → SECRET_KEY_FILE（なければ作る）→ 開発用の固定値、の順。"""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.environ.get("SECRET_KEY_FILE")
    if path:
        p = Path(path)
        if not p.exists():
            from django.core.management.utils import get_random_secret_key

            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(get_random_secret_key(), encoding="utf-8")
        return p.read_text(encoding="utf-8").strip()
    return "django-insecure-tollroute-local-development"


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# スマホから Tailscale 経由で使うときの PC の名前（例: my-pc.tail1234.ts.net）。docs/remote-access.md
EXTRA_ALLOWED_HOSTS = [h.strip() for h in os.environ.get("EXTRA_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS += EXTRA_ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in EXTRA_ALLOWED_HOSTS]
# tailscale serve は HTTPS を受けて HTTP で中継する
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if EXTRA_ALLOWED_HOSTS else None

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "routes",
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
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
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
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.environ["DATABASE_URL"], engine="django.contrib.gis.db.backends.postgis"
    ),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "data" / "staticfiles"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)  # collectstatic 前でも WhiteNoise が警告しないように
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
