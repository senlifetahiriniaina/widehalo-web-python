from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-secret-key"  # noqa: S105 (settings de test uniquement)

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

Q_CLUSTER = {  # noqa: F405
    "name": "widehalo-test",
    "sync": True,
    "retry": 120,
    "timeout": 60,
}

AXES_ENABLED = False

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
