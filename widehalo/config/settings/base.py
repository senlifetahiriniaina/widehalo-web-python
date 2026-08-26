from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(str(REPO_ROOT / ".env"))

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_htmx",
    "guardian",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "axes",
    "django_q",
    "channels",
    "ninja_jwt",
    "ninja_jwt.token_blacklist",
    # Apps du socle WideHalo
    "apps.core",
    "apps.chat",
    "apps.partners",
    "apps.catalog",
    # Modules metier du Lot 2 (Madagascar)
    "apps.accounting",
    "apps.crm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "axes.middleware.AxesMiddleware",
    # TenantMiddleware doit s'executer APRES AuthenticationMiddleware (a besoin de
    # request.user pour resoudre les tenants autorises) mais AVANT toute vue/API
    # qui accede a l'ORM. Ne jamais deplacer avant Authentication.
    "apps.core.middleware.TenantMiddleware",
    "apps.core.middleware.MFAEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB", default="widehalo"),
        "USER": env.str("POSTGRES_USER", default="widehalo_app"),
        "PASSWORD": env.str("POSTGRES_PASSWORD", default="widehalo_app"),
        "HOST": env.str("POSTGRES_HOST", default="db"),
        "PORT": env.str("POSTGRES_PORT", default="5432"),
    }
}

AUTH_USER_MODEL = "core.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"

AUTHENTICATION_BACKENDS = [
    # AxesBackend doit etre EN PREMIER : il intercepte les tentatives et
    # bloque avant de deleguer aux backends suivants (cf. doc django-axes).
    "axes.backends.AxesBackend",
    "django.contrib.auth.backends.ModelBackend",
    "guardian.backends.ObjectPermissionBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.core.services.password_validators.CompromisedPasswordValidator"},
]

# Internationalisation (etape 6) : francais par defaut, anglais disponible.
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
DISPLAY_TIME_ZONE = "Indian/Antananarivo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = REPO_ROOT / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = REPO_ROOT / "data" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions / securite (etape 4) ---
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --- django-axes (verrouillage apres echecs, etape 4) ---
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # heure
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]

# --- Redis / cache / Django-Q2 (etape 9) ---
REDIS_URL = env.str("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

Q_CLUSTER = {
    "name": "widehalo",
    "redis": REDIS_URL,
    "retry": 60,
    "timeout": 50,
    "max_attempts": 3,
    "workers": 2,
    "sync": False,
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

PASSWORD_RESET_TIMEOUT = 3600  # 1h, exigence normative du cahier des charges

# --- JWT (ninja-jwt, etape 4) ---
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# --- Antivirus (etape 10) ---
CLAMAV_ENABLED = env.bool("CLAMAV_ENABLED", default=False)

# --- WhatsApp Business API (etape 11) ---
WHATSAPP_ENABLED = env.bool("WHATSAPP_ENABLED", default=False)
WHATSAPP_PHONE_NUMBER_ID = env.str("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_ACCESS_TOKEN = env.str("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_WEBHOOK_VERIFY_TOKEN = env.str("WHATSAPP_WEBHOOK_VERIFY_TOKEN", default="")

# --- Roles standards (etape 5) ---
CORE_STANDARD_ROLES = [
    "admin",
    "direction",
    "comptable",
    "commercial",
    "resp_commercial",
    "acheteur",
    "resp_production",
    "chef_atelier",
    "magasinier",
    "rh",
    "collaborateur",
]
CORE_MFA_REQUIRED_ROLES = {"admin", "direction", "comptable", "rh"}
CORE_SIMPLE_MODE_ROLES = {"collaborateur", "magasinier", "chef_atelier"}

# --- Garde-fous d'architecture (etape 2) ---
BUDGET_MAX_MODELS = 180
BUDGET_MAX_ENDPOINTS = 600
BUDGET_MAX_SCREENS = 90

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
