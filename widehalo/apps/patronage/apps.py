from django.apps import AppConfig


class PatronageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patronage"
    label = "patronage"
    verbose_name = "Patrons et gradation"
