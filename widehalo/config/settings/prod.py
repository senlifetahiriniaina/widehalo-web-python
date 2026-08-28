from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY as _BASE_SECRET_KEY
from .base import env

DEBUG = False

# base.py falls back to a well-known insecure default (dev convenience) when
# DJANGO_SECRET_KEY isn't set. In production that must never happen silently.
# Sentinel comparison against base.py's known dev-fallback string, not a real secret.
if _BASE_SECRET_KEY == "insecure-dev-key-change-me":  # noqa: S105 # nosec B105
    raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable must be set in production.")

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# TLS est terminee par le reverse proxy (Caddy, cf. docker-compose.prod.yml) —
# jamais par Django lui-meme. Sans cet en-tete, request.is_secure() renvoie
# toujours False derriere le proxy (la connexion Django<->Caddy est en clair
# sur le reseau Docker interne) et SECURE_SSL_REDIRECT ci-dessus boucle
# indefiniment. Caddy est le seul frontal HTTP admis dans ce lot : il fixe
# X-Forwarded-Proto lui-meme, jamais transmis tel quel depuis l'exterieur.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Origines autorisees pour les requetes POST avec cookie de session (formulaires
# HTMX de ce socle) — distinct de DJANGO_ALLOWED_HOSTS (Host: header) : Django
# exige un schema explicite ici. Sans ceci, tout POST depuis le sous-domaine
# configure echoue en "CSRF verification failed" une fois SECURE_SSL_REDIRECT
# actif. Valeur typique : https://app.widehalo.cloud (cf. docs/DEPLOYMENT_HETZNER.md).
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
