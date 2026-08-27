from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY as _BASE_SECRET_KEY

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
