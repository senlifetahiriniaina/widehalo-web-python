from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="forecast",
    # "analytics" : historique des séries (ventes/encaissements) déjà
    # matérialisé par l'entrepôt en étoile (cahier Phase 2 §12) — SEULE
    # source d'historique pour le pipeline STATISTIQUE existant (séries/
    # rétrotest/publication), jamais un accès direct à `sales`/`pos`/
    # `accounting` POUR CE PIPELINE (cf. §13.2 : "les séries de
    # prévision proviennent de l'entrepôt, dépendance stricte, pas de
    # parallélisation").
    #
    # Bloc F, F1 (§13.2, « besoin matière prévisionnel ») :
    # `services/material_needs.py` est un pipeline DISTINCT — une
    # confrontation en TEMPS RÉEL (pas un historique reconstruit) de la
    # demande déjà prévue (`sales.SalesForecast`, PAS `ForSeriesForecast`
    # — cf. docstring `models.py`) à l'état courant du stock/réservations
    # (`stocks`), des commandes fournisseur en cours (`purchase`) et de
    # la nomenclature (`mrp`, via `catalog` pour résoudre variante ->
    # template) — cette exception ne s'applique JAMAIS au pipeline
    # statistique ci-dessus, qui reste strictement borné à `analytics`.
    dependencies=("core", "analytics", "sales", "mrp", "stocks", "purchase", "catalog"),
    verbose_name="Prévision (ventes, encaissements, trésorerie, besoin matière)",
)
