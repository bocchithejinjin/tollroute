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
# 先頭が「.」のもの（例: .trycloudflare.com）は、そのドメインのサブドメインすべてを許可する
CSRF_TRUSTED_ORIGINS = [f"https://*{h}" if h.startswith(".") else f"https://{h}" for h in EXTRA_ALLOWED_HOSTS]
# 管理画面は既定では DEBUG のときだけ有効（公開中は外から開けない）
ENABLE_ADMIN = os.environ.get("ENABLE_ADMIN", "true" if DEBUG else "false").strip().lower() in {"1", "true", "yes", "on"}
# 検索 API の回数制限（1 つの接続元から 1 分あたり）
SEARCH_RATE_LIMIT_PER_MIN = int(os.environ.get("SEARCH_RATE_LIMIT_PER_MIN", "30"))


def _google_routes_api_key() -> str:
    """Google Routes API のキー: 環境変数 → GOOGLE_ROUTES_API_KEY_FILE（あれば）。どちらもなければ使わない。"""
    if os.environ.get("GOOGLE_ROUTES_API_KEY", "").strip():
        return os.environ["GOOGLE_ROUTES_API_KEY"].strip()
    path = os.environ.get("GOOGLE_ROUTES_API_KEY_FILE", "").strip()
    if path and Path(path).is_file():
        key = Path(path).read_text(encoding="utf-8").strip()
        # Windows の DPAPI で暗号化したファイル（ConvertFrom-SecureString の出力）はここでは読めない
        if not key.lower().startswith("01000000d08c9ddf"):
            return key
    return ""


# 設定すると、経路の所要時間と ETC 料金を Google Routes API で確かめるモードになる（docs/google-routes.md）
GOOGLE_ROUTES_API_KEY = _google_routes_api_key()
# Google を使う検索の 1 日（日本時間）あたりの上限（ワーカーごと）。超えたら自作エンジンだけで答える。0 で無制限
GOOGLE_ROUTES_DAILY_SEARCHES = int(os.environ.get("GOOGLE_ROUTES_DAILY_SEARCHES", "30"))
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
