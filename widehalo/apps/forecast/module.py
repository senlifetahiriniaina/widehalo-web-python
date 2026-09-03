from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="forecast",
    # "analytics" : historique des séries (ventes/encaissements) déjà
    # matérialisé par l'entrepôt en étoile (cahier Phase 2 §12) — SEULE
    # source d'historique, jamais un accès direct à `sales`/`pos`/
    # `accounting` (cf. §13.2 : "les séries de prévision proviennent de
    # l'entrepôt, dépendance stricte, pas de parallélisation").
    dependencies=("core", "analytics"),
    verbose_name="Prévision (ventes, encaissements, trésorerie)",
)
