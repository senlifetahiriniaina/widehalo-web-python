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
    # "accounting" ajoute par ST5 (RG-STK-9, cf. plan) : premiere fois que
    # `stocks` consomme `accounting.services.public.
    # create_stock_adjustment_entry_from_source` (`services/inventory.py`,
    # ecriture comptable de regularisation automatique a la validation
    # d'un inventaire) — jamais `apps.accounting.models`.
    # "mrp" ajoute par ST6 (RG-STK-6, cf. plan) : premiere fois que
    # `stocks` consomme `mrp.services.public.list_closed_orders`/
    # `get_order_produced_qty` (`services/consistency.py`, cohérence
    # production/stock) — jamais `apps.mrp.models`.
    # "sales" ajoute par ST6 (RG-STK-6, cf. plan) : premiere fois que
    # `stocks` consomme `sales.services.public.get_delivered_qty_for_order`
    # (`services/consistency.py`) — jamais `apps.sales.models`.
    dependencies=("core", "catalog", "purchase", "accounting", "mrp", "sales"),
    verbose_name="Stocks",
)
