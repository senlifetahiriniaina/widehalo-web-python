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
    # Socle Tailwind/DaisyUI/django-cotton de la refonte UX (Sprint 0, cf.
    # docs/planning/2026-refonte-ux-sprints.md) : composants dans
    # templates/cotton/, invoques <c-nom-composant>. Se configure tout
    # seul (loaders + builtins) via django_cotton.apps.LoaderAppConfig.
    "django_cotton",
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
    "apps.pos",
    "apps.simulation",
    "apps.analytics",
    "apps.bi",
    "apps.forecast",
    "apps.whatsapp",
    "apps.quality",
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
    # Sprint 10 (L6 Personnalisation) : APRES LocaleMiddleware (l'override
    # explicitement, cf. sa docstring) et APRES AuthenticationMiddleware
    # (a besoin de request.user pour lire `preferred_language`) -- ne
    # jamais la deplacer avant l'une des deux.
    "apps.core.middleware.UserLocaleMiddleware",
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
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.tenant",
                "apps.core.context_processors.account",
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
# "mg" (Malagasy) ajoute au Sprint 10 (L6 Personnalisation) -- catalogue
# `locale/mg/` volontairement vide pour l'instant, cf. sa note d'en-tete et
# `apps.core.models.user.PREFERRED_LANGUAGE_CHOICES`.
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English"), ("mg", "Malagasy")]
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

# UXR1 : base absolue pour un lien de confirmation envoye par e-mail
# (`apps.core.services.email_change.request_email_change`) — aucune
# variable Django `SITE_URL`/equivalente n'existait avant ce chantier (seul
# `WIDEHALO_DOMAIN`, cf. .env.example, pilote Caddy/le certificat TLS, sans
# jamais etre lu par le code applicatif). `SITE_URL` par defaut sur
# `http://localhost:8000` (dev) ; en production, exposer
# `SITE_URL=https://app.widehalo.cloud` via .env (memes valeurs que
# `WIDEHALO_DOMAIN`, prefixees du schema).
SITE_URL = env.str("SITE_URL", default="http://localhost:8000")

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
# module `apps.whatsapp` (gouvernance, cahier Phase 2 §13.4) : le compte
# WhatsApp Business ci-dessus (WHATSAPP_PHONE_NUMBER_ID) reste un numero
# GLOBAL unique pour tout le deploiement (pas un numero par tenant — meme
# limitation deja presente dans le socle `core` avant ce chantier) ; ce
# reglage resout donc a QUEL tenant rattacher un message entrant recu par
# le webhook gouverne (`apps.whatsapp.api::whatsapp_webhook_receive`).
# Vide par defaut : le webhook gouverne se degrade alors sur la seule
# journalisation deja existante (`core.services.notifications.
# record_inbound_whatsapp_message`), sans aucune gouvernance appliquee —
# jamais une exception. Un vrai routage par tenant (plusieurs numeros
# WhatsApp Business, un par tenant) resterait a construire si ce besoin
# multi-tenant reel se confirme — hors perimetre disclosed de ce chantier.
WHATSAPP_DEFAULT_TENANT_ID = env.str("WHATSAPP_DEFAULT_TENANT_ID", default="")

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
# "caissier" ajoute par le chantier module POS (cahier Phase 1 §13.5,
# persona "Caissier / vendeur" explicitement nomme §3 : "encaisse face a
# une file d'attente... souvent peu forme, parfois saisonnier") — 12e role,
# le premier ajoute depuis les 11 roles "V1 acquis du CDC" (cf. tous les
# roles precedents, qui reutilisent un role existant "faute d'un role
# dedie" : magasinier/logistics, acheteur/departement achats...). Aucun des
# 11 roles existants ne convient : `commercial` porte deja un scope N3
# "own" distinct (portefeuille CRM/ventes) sans rapport avec "sa session de
# caisse", et le cahier nomme litteralement ce persona a part du
# commercial (activites/contexte d'usage entierement differents — cf.
# docs/RBAC.md §2 pour le detail de cette decision). Rattache a
# `CORE_SIMPLE_MODE_ROLES` (meme discipline que `magasinier`/
# `chef_atelier` : role intensif mais peu forme, interface guidee).
#
# "controleur_gestion" ajoute par le chantier module Simulation financiere
# (cahier Phase 1 §13.6, persona "Controleur de gestion" explicitement
# nomme §3 : "manipuler des hypotheses sur les vraies donnees et voir
# l'effet immediatement... aujourd'hui dans un tableur deconnecte des
# donnees") — 13e role. Meme raisonnement que `caissier` : aucun role
# existant ne convient (le cahier reserve explicitement l'atelier de
# scenarios et l'outil IA `paramétrer_simulation` à "Contrôleur de
# gestion, Dirigeant" — un role de pilotage utilisateur EXPERT, distinct
# de `direction` qui porte deja un role de pilotage/validation TRANSVERSE
# sur tous les autres modules, cf. `ROLE_APP_PERMISSIONS["direction"]`).
# PAS rattache a `CORE_SIMPLE_MODE_ROLES` : role expert (cf. persona,
# "Utilisateur periodique, a fort pouvoir de decision"), pas un role
# intensif peu forme comme `caissier`/`magasinier`/`chef_atelier`.
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
    "caissier",
    "controleur_gestion",
]
CORE_MFA_REQUIRED_ROLES = {"admin", "direction", "comptable", "rh"}
CORE_SIMPLE_MODE_ROLES = {"collaborateur", "magasinier", "chef_atelier", "caissier"}

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
# Le plafond de 215 ecrans n'avait plus que 15 de marge (200/215) a la
# cloture de HD3 (base de connaissances/gabarits de reponse/chat interne du
# module `helpdesk`), avec HD4-HD6 (rapports combines CSAT/performance
# agents/conformite SLA, puis integration IA/automatisation transversale,
# puis finalisation) encore a livrer, en plus du pays #2 a venir sur cette
# meme base — **Decision explicite actee avec l'utilisateur** (meme
# precedent que chaque relevement precedent) : relever BUDGET_MAX_MODELS a
# 290 et BUDGET_MAX_SCREENS a 240, marge confortable pour le reste de
# `helpdesk` et le demarrage du pays #2 sans avoir a re-relever a chaque
# etape restante.
# Le plafond de 290 modeles a ete atteint EXACTEMENT (290/290, zero marge) a
# la cloture du Bloc C (Production, plan Phase 3) — confirme en tete du
# Bloc D (Qualite/HACCP, decision D2, cf. `docs/planning/2026-09-adr-
# qualite-haccp-app-dediee.md`) : nouvelle app dediee `apps.quality`
# necessitant au minimum 4 modeles reels des D1 (plan de controle, point
# critique, mesure, non-conformite bloquante — un domaine de conformite/
# audit qui a besoin de lignes interrogeables individuellement, pas d'un
# sac JSONField comme les simplifications deja pratiquees ailleurs pour
# economiser le budget), plus une marge realiste pour D2/D4/D5 (certificat
# obligatoire, eventuel dossier de rappel dedie, decision de migration des
# modeles qualite existants) — **Decision explicite actee avec
# l'utilisateur** (meme precedent que chaque relevement precedent) :
# relever BUDGET_MAX_MODELS a 310, marge de 20 pour l'integralite du
# Bloc D sans avoir a re-relever a chaque sprint D1-D5.
# Le plafond d'ecrans est atteint EXACTEMENT (240/240, zero marge) — mesure
# officielle du 2026-09-05 par le compteur de `tests/architecture/
# test_budget.py` : 300 modeles / 576 endpoints / 240 ecrans. C'est le
# troisieme plafond a saturer exactement, apres les modeles a deux reprises.
# Trois chantiers immediatement engages en ont chacun besoin, et le premier
# gabarit ajoute ferait echouer la construction : D10 (abstraction du
# referentiel comptable PCG 2005/SYSCOHADA, critere ACC-2 — ~4 modeles et
# un ecran de parametrage des comptes par defaut du tenant), L0
# (ordonnanceur — un ecran d'exploitation listant derniere execution, duree
# et issue des 19 commandes periodiques) et la Vague 1 du plan de
# rattrapage, dont quatre lots livrent au moins un gabarit (POS impression
# de ticket, qualite liste des controles, CRM kanban et etat vide, BI
# composition de tableau de bord). Aucune economie n'est possible ici sans
# refaire ce que les relevements precedents ont deja refuse : fusionner des
# ecrans distincts derriere des onglets degrade le patron "un fichier par
# ecran" applique partout ailleurs, et fusionner des modeles de conformite
# dans un JSONField supprime l'auditabilite ligne a ligne, precisement ce
# que le Bloc D avait ecarte. **Decision explicite actee avec
# l'utilisateur** (meme precedent que chaque relevement precedent, cf.
# docstring de `tests/architecture/test_budget.py`) : relever les TROIS
# plafonds de +33 %, d'un seul mouvement couvrant D10, L0 et l'integralite
# de la Vague 1, plutot qu'un relevement par lot — 310 -> 415 modeles
# (+33,9 %), 600 -> 800 endpoints (+33,3 %), 240 -> 320 ecrans (+33,3 %).
# RESERVE A CONNAITRE AVANT LA PHASE 4 : ce relevement ne la couvre pas.
# Le cahier des charges Phase 4 (§11.1, `docs/cdc-complet/phase-4-
# connectivite-et-integrations.md`) projette 430 modeles / 1 210 endpoints
# / 278 ecrans, plus deux budgets nouveaux (12 adaptateurs, 80 operations
# publiques). Les ecrans sont donc couverts (320 > 278), mais les modeles
# (415 < 430) et surtout les endpoints (800 < 1 210, l'ecart venant presque
# entierement de la surface d'API publique du bloc B) exigeront un SECOND
# relevement au demarrage de la Phase 4. Ce n'est pas un oubli : le
# perimetre assume de celui-ci est D10 + L0 + Vague 1.
BUDGET_MAX_MODELS = 415
BUDGET_MAX_ENDPOINTS = 800
BUDGET_MAX_SCREENS = 320

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
#
# Sprint 11 (L7 IA gateway) : le CDC nomme explicitement un "repli Mistral"
# comme fournisseur cloud de secours. L'API Mistral ("La Plateforme") est
# elle aussi compatible OpenAI chat-completions, donc couverte par le meme
# `OpenAICompatibleAIProvider` — AUCUN nouveau connecteur necessaire, un
# simple exemple de configuration documente ici, additionnel a l'exemple
# DeepSeek/Kimi ci-dessus (ne le remplace pas) :
# {"backend": "mistral", "base_url": "https://api.mistral.ai/v1",
# "api_key": "...", "model": "mistral-small-latest"}. Comme pour
# DeepSeek/Kimi/Ollama, "backend" reste une simple etiquette de diagnostic
# (`AiRequest.provider_backend`, cf. `apps.ai.services.usage_budget.
# _resolve_backend_label`) — un seul fournisseur est actif a la fois
# (celui configure dans `AI_PROVIDER_CONFIG`), il n'y a pas ici de chaine
# de repli automatique multi-fournisseurs.
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
