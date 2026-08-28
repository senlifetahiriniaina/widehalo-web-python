from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="accounting",
    # "stocks" ajoute par le chantier de durcissement retroactif qui leve
    # le stub A17/ACC-IMP (`stocks` n'existait pas encore quand `accounting`
    # a ete construit, cf. plan) : `services.landed_costs.finalize_batch`
    # consomme desormais `apps.stocks.services.public.
    # apply_landed_cost_to_valuation` — jamais `apps.stocks.models`.
    # "catalog" et "accounting" ajoutes par le chantier RG-QUALIF :
    # `services.invoice_import` consomme `apps.catalog.services.public.
    # ensure_default_variant`/`get_variant_id_by_reference`, et reutilise
    # `apps.accounting.services.public.create_customer_invoice_from_
    # source`/`create_supplier_invoice_from_source` (deja construits pour
    # `sales`/`purchase`) plutot que de dupliquer la construction de
    # facture — un import explicite de son propre `services.public`,
    # declare ici comme tout autre gap consomme.
    dependencies=("core", "partners", "stocks", "catalog", "accounting"),
    verbose_name="Comptabilite",
)
