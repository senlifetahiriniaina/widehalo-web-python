from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="stocks",
    # "catalog" ajoute par ST3 (RG-STK-5, cf. plan) : premiere fois que
    # `stocks` consomme `catalog.services.public.convert_textile_measurement`
    # (`services/measurements.py`) — jamais `apps.catalog.models`.
    # "purchase" ajoute par ST3 (RG-STK-4, cf. plan) : premiere fois que
    # `stocks` consomme `purchase.services.public.open_purchase_incident`
    # (`services/measurements.py`, ouverture automatique d'un litige
    # fournisseur au-dela du seuil d'ecart de mesure) — jamais
    # `apps.purchase.models`.
    dependencies=("core", "catalog", "purchase"),
    verbose_name="Stocks",
)
