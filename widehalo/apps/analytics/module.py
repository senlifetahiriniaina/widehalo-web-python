from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="analytics",
    # Cahier Phase 2 §12 (fondations decisionnelles, prealable aux modules
    # BI/Forecast/Strategy/WhatsApp) : l'entrepot en etoile est alimente par
    # extraction depuis les modules metier deja construits, jamais par
    # import direct de leurs modeles (regle de couplage n°1) — seulement
    # leurs nouveaux gaps `list_*_for_warehouse()`/`iter_*_for_warehouse()`
    # de `services/public.py`.
    # "sales" : `AnFactVente` (lignes de commande).
    # "pos" : `AnFactTicketPos` (lignes de ticket).
    # "accounting" : `AnFactEncaissement`/`AnFactEcriture` (paiements et
    # ecritures publiees) + referentiel des comptes PCG.
    # "catalog" : `AnDimArticle` (variantes vendables ou non).
    # "partners" : `AnDimTiers` (clients/fournisseurs).
    # "stocks" : `AnFactMouvementStock` (mouvements de stock valides,
    # Bloc Transverse T1).
    dependencies=("core", "sales", "pos", "accounting", "catalog", "partners", "stocks"),
    verbose_name="Analytique (entrepôt & indicateurs)",
)
