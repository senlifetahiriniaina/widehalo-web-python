from django.apps import AppConfig


class FinancingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.financing"
    label = "financing"
    verbose_name = "Financement bancaire PME"

    # Note : `ready()` n'enregistre le registre `reporting` (FIN-DOSSIER/
    # FIN-CREDOC) qu'a partir de FIN4 (cf. `services/reports_registration.py`,
    # meme sequencement que `strategy` — STRATEGY-BP n'a ete cable qu'a STR3,
    # pas des STR1) — pas de hook prematurement dependant d'un module qui
    # n'existe pas encore a FIN1/FIN2/FIN3.
