from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env():
    for env_path in (BASE_DIR.parent / ".env", BASE_DIR / ".env"):
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_local_env()


# ==============================
# SECURITY
# ==============================

SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-key")

DEBUG = os.getenv("DEBUG", "True") == "True"


# ==============================
# HOSTS
# ==============================

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")

if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)


# ==============================
# CSRF
# ==============================

CSRF_TRUSTED_ORIGINS = []

if RENDER_HOST:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")


# ==============================
# APPLICATIONS
# ==============================

INSTALLED_APPS = [
    "jazzmin", 
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "accounts.apps.AccountsConfig",
    "academics",
    "companies.apps.CompaniesConfig",
    "placements",
    "tracking",
]


# ==============================
# MIDDLEWARE
# ==============================

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


# ==============================
# URLS
# ==============================

ROOT_URLCONF = "config.urls"


# ==============================
# TEMPLATES
# ==============================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        # ✅ works locally & on Render
        "DIRS": [BASE_DIR / "templates"],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ==============================
# WSGI
# ==============================

WSGI_APPLICATION = "config.wsgi.application"


# ==============================
# DATABASE
# ==============================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ==============================
# PASSWORDS
# ==============================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ==============================
# INTERNATIONALIZATION
# ==============================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"

USE_I18N = True
USE_TZ = True


# ==============================
# STATIC FILES (CRITICAL PART)
# ==============================

STATIC_URL = "/static/"

# used locally
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# used by Render
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
)


# ==============================
# MEDIA FILES
# ==============================

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ==============================
# AUTH
# ==============================

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


# ==============================
# EMAIL
# ==============================

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    (
        "django.core.mail.backends.smtp.EmailBackend"
        if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
        else "django.core.mail.backends.console.EmailBackend"
    ),
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False") == "True"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "ghabbala@gmail.com",
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL



JAZZMIN_SETTINGS = {
    # Titles
    "site_title": "VU Admin",
    "site_header": "Victoria University",
    "site_brand": "VU Admin",

    # Welcome text on login screen
    "welcome_sign": "Welcome to the Victoria University Internship System",

    # Logo (optional)
    # Put a file in: static/img/vu-logo.png
    "site_logo": "base/img/vu_logo.jpg",
    "site_logo_classes": "img-circle",

    # Icon on browser tab
    #"site_icon": "img/vu-favicon.png",

    # Footer
    "copyright": "© Victoria University",

    # Search bar model (optional)
    # Use a model you have, e.g. accounts.User
    "search_model": "accounts.User",

    # Sidebar / menu ordering (optional, but makes it clean)
    "order_with_respect_to": [
        "accounts",
        "placements",
        "companies",
        "tracking",
        "auth",
    ],

    # Custom links on top menu
    "topmenu_links": [
        {"name": "Dashboard", "url": "admin:index", "permissions": ["auth.view_user"]},
    ],

    # Show UI builder (lets you tweak layout in the admin UI)
    "show_ui_builder": True,
    "custom_css": "admin/css/vu_admin.css",
}
