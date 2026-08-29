from .base import *  # noqa: F403

DEBUG = False
# Test-only key, never used in prod (base/prod settings pull SECRET_KEY from the environment).
SECRET_KEY = "test-secret-key-not-for-production-use-only-32bytes+"  # noqa: S105 # nosec B105

# Deliberately weak/fast hasher for the test suite only (real user passwords are never
# processed through this settings module) — trades cryptographic strength for test speed.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

Q_CLUSTER = {  # noqa: F405
    "name": "widehalo-test",
    "sync": True,
    "retry": 120,
    "timeout": 60,
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# §5.11 reporting RPT-6 : seuil abaisse a l'extreme pour demontrer le
# mecanisme d'asynchronisme (test d'acceptance n°4) sans materialiser
# 50 000 lignes reelles en fixture — cf. docstring `apps.reporting.services.
# engine`.
REPORTING_ASYNC_THRESHOLD_SECONDS = 0.01

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
