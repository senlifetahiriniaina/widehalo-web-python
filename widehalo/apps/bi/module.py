from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="bi",
    # "analytics" : entrepôt en étoile + dictionnaire d'indicateurs
    # gouverné (cahier Phase 2 §12, `apps.analytics.services.public`) —
    # SEULE source de données décisionnelles, jamais un accès direct à
    # `sales`/`accounting`/`pos`/etc. (le moteur de requête guidé de `bi`
    # interroge exclusivement les faits/dimensions déjà matérialisés par
    # `analytics`, cf. `services/query.py`).
    # "reporting" : réutilise intégralement le mécanisme `RptJob`/
    # `generate_report` déjà construit (seuil d'asynchronie, notification,
    # purge à 7 jours, écrans de suivi/téléchargement) pour l'export BI-8,
    # via le nouveau gap `reporting.services.public.enqueue_report_
    # generation` — `bi` n'a donc aucun modèle de job d'export à lui.
    dependencies=("core", "analytics", "reporting"),
    verbose_name="Business Intelligence",
)
