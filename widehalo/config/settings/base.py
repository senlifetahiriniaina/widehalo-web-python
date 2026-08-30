from datetime import timedelta
from decimal import Decimal
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
    "apps.mrp",
    "apps.patronage",
    "apps.sales",
    "apps.purchase",
    "apps.stocks",
    "apps.logistics",
    "apps.presence",
    "apps.payroll",
    "apps.reporting",
    "apps.strategy",
    "apps.financing",
    "apps.automation",
    "apps.feasibility",
    "apps.projects",
    "apps.ai",
    "apps.helpdesk",
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
    # OnboardingMiddleware AVANT MFAEnforcementMiddleware : changer le mot de
    # passe temporaire du compte admin par defaut avant d'enroler MFA dessus.
    "apps.core.middleware.OnboardingMiddleware",
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

# --- Veille prix fournisseurs Chine/Europe (PRC1-3) ---
# Dict vide par defaut = TOUTE plateforme utilise `StubPriceSourceProvider`
# (aucun appel reseau). Cf. `apps.purchase.services.price_watch` (docstring
# de tete) pour la reserve de securite/legalite complete : un scraping HTTP
# reel de plateformes commerciales (CGU l'interdisant souvent) n'est jamais
# active par ce projet — seul un utilisateur remplissant explicitement cette
# configuration, apres verification des CGU de la plateforme concernee,
# peut faire basculer une plateforme vers un connecteur reel (forme
# attendue : {"alibaba": {"base_url": "...", "api_key": "..."}}).
PRICE_WATCH_PROVIDERS: dict[str, dict[str, str]] = {}

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

# --- CRM : plafonds de remise par role (RG-CRM-3), etape C2 du Lot 2 ---
# Un role absent de ce mapping (direction, admin...) reste illimite par
# conception — seuls les roles explicitement plafonnes ci-dessous
# declenchent une demande de validation au-dela du seuil.
CRM_DISCOUNT_CAP_BY_ROLE = {
    "commercial": Decimal(10),
    "resp_commercial": Decimal(25),
}

# --- Garde-fous d'architecture (etape 2) ---
# Plafonds V1 initiaux du CDC : 180 modeles / 600 endpoints / 90 ecrans,
# pour un perimetre de 13 modules metier. Le Lot 2 a depuis largement
# depasse ce perimetre (12 modules metier + financing + extension
# sectorielle + Cote d'Ivoire a venir) sur decision actee avec
# l'utilisateur des le debut du Lot 2 — les plafonds MODELES/ENDPOINTS
# n'ont jamais ete revus depuis (146/180 et 248/600 a la cloture de
# `stocks`, encore de la marge). Le plafond ECRANS, lui, a ete atteint
# EXACTEMENT (90/90) a la finalisation de `stocks` (ST8) : l'agent avait
# du regrouper la totalite de ses ecrans dans une seule page multi-onglets
# pour rester dans la lettre du compteur (base sur le nombre de fichiers
# .html, cf. tests/architecture/test_budget.py::_counted_screens), au prix
# d'une derogation au patron "un fichier par ecran" applique partout
# ailleurs dans ce depot. Avec 6+ modules metier restants (logistics,
# financing, presence, payroll, reporting, strategy) plus l'extension
# sectorielle, ce plafond aurait bloque toute construction d'ecran des le
# module suivant. **Decision explicite actee avec l'utilisateur** (le
# plafond ne doit JAMAIS etre releve sans une telle decision, cf. docstring
# de `tests/architecture/test_budget.py`) : relever BUDGET_MAX_SCREENS a
# 200 (marge proportionnee a celle deja observee sur MODELES/ENDPOINTS),
# pour laisser aux modules restants la possibilite de revenir au patron
# normal "un fichier par ecran" plutot que de generaliser la consolidation
# mono-page de `stocks` par necessite budgetaire — celle-ci reste un cas
# particulier documente dans `apps/stocks/views.py`, pas le nouveau
# standard du depot.
# MODELES : le plafond de 180 a ete atteint EXACTEMENT (180/180, zero marge)
# a la cloture de `presence`, deja signale a ce moment comme bloquant pour
# tout chantier suivant sans augmentation explicite. Le module `payroll`
# (5.10 CDC) porte 11 entites nommement listees par le CDC, dont la fusion
# artificielle degraderait l'auditabilite d'un domaine deja tres reglemente
# (IRSA/CNaPS/OSTIE) — **Decision explicite actee avec l'utilisateur** (meme
# precedent que le relevement de BUDGET_MAX_SCREENS 90->200 a l'etape ST8 de
# `stocks`, cf. paragraphe ci-dessus) : relever BUDGET_MAX_MODELS a 220,
# marge proportionnee pour `payroll` et les chantiers restants (reporting,
# strategy, financing, extension sectorielle, pays #2).
# Le plafond de 220 a ete atteint EXACTEMENT (220/220, zero marge) a la
# cloture du chantier PRC1-3 (veille prix fournisseurs). Le module `projects`
# (gestion de projets, porte depuis l'ancienne version WideHalo) necessite
# ~10 nouveaux modeles economises (hierarchie epic/tache/jalon unifiee dans
# un seul PrjTask, etc.) — **Decision explicite actee avec l'utilisateur**
# (meme precedent que les deux relevements precedents ci-dessus) : relever
# BUDGET_MAX_MODELS a 250, marge de 20 au-dela des besoins de ce chantier
# pour la suite du Lot 2 Madagascar et le demarrage du pays #2.
# Le plafond de 250 modeles n'avait plus que 13 de marge (237/250) et celui
# de 200 ecrans seulement 10 (190/200) au moment d'attaquer le module
# `helpdesk` (suivi des demandes/incidents operationnels, porte depuis
# l'ancienne version WideHalo, perimetre reduit au strict interne — pas de
# portail client/chat visiteur/forum, decision actee explicitement avec
# l'utilisateur). Le perimetre retenu (11 nouveaux modeles economises,
# ~10 ecrans) rentrait tout juste dans cette marge mais l'aurait epuisee
# integralement — **Decision explicite actee avec l'utilisateur** (meme
# precedent que les relevements precedents ci-dessus, HD0) : relever
# BUDGET_MAX_MODELS a 265 et BUDGET_MAX_SCREENS a 215, marge modeste pour
# la suite du Lot 2 Madagascar et le demarrage du pays #2.
BUDGET_MAX_MODELS = 265
BUDGET_MAX_ENDPOINTS = 600
BUDGET_MAX_SCREENS = 215

# Chantier `projects` : configuration du connecteur IA generique
# (`apps.core.services.ai_assistant`). Dictionnaire VIDE par defaut — le
# `StubAIProvider` reste actif tant qu'aucune cle n'est fournie explicitement
# (meme discipline que WHATSAPP_ENABLED/PRICE_WATCH_PROVIDERS deja dans ce
# depot : jamais d'appel reseau reel sans configuration explicite de
# l'utilisateur). Cles attendues si renseigne : {"backend": "deepseek"|
# "kimi"|"custom", "api_key": "...", "base_url": "...", "model": "..."} —
# DeepSeek et Kimi (Moonshot AI) exposent tous deux une API "chat
# completions" compatible OpenAI, d'ou un connecteur HTTP unique
# (`OpenAICompatibleAIProvider`) plutot que trois implementations separees.
# Chantier module `ai` (AI1) : la cle "backend" est desormais reellement
# lue (par `apps.ai.services.usage_budget._resolve_backend_label`) pour
# peupler `AiRequest.provider_backend` a des fins de diagnostic/cout —
# `get_ai_provider()` lui-meme continue de l'ignorer, elle ne pilote jamais
# quel connecteur est instancie (seuls `base_url`/`api_key` le font).
# AI8 : pour pointer vers le conteneur Ollama auto-heberge optionnel
# (`docker compose --profile local-ai up`, cf. docs/AI_MODULE.md) :
# {"backend": "local-ollama", "base_url": "http://ai-runtime:11434/v1",
# "api_key": "ollama", "model": "qwen2.5:7b"} — `api_key` est une valeur
# factice non verifiee par Ollama (son endpoint compatible OpenAI ignore
# l'en-tete Authorization), mais requise non-vide par
# `OpenAICompatibleAIProvider`/`get_ai_provider()` ci-dessus.
AI_PROVIDER_CONFIG: dict[str, str] = {}

# §5.11 reporting, RPT-6 (test d'acceptance n°4, generation asynchrone) :
# au-dela de ce nombre de secondes ESTIME (cf. `apps.reporting.services.
# engine._should_run_async` — estimation grossiere, jamais une mesure
# reelle) un rapport part en asynchrone via `core.tasks.enqueue()` plutot
# que d'etre genere dans le thread de la requete web. Abaisse a l'extreme en
# test (`config.settings.test`) pour demontrer le mecanisme bout en bout
# sans avoir a materialiser un vrai jeu de 50 000 lignes en fixture —
# disclosed, cf. docstring `engine.py`.
REPORTING_ASYNC_THRESHOLD_SECONDS = 30.0
# RPT-6 : duree de conservation du fichier genere avant purge (meme patron
# que `sandbox.DEFAULT_EXPIRY_DAYS`) — 7 jours conformement au CDC.
REPORTING_JOB_RETENTION = timedelta(days=7)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
