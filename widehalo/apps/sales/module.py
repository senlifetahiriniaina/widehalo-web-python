from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="sales",
    # "stocks"/"purchase" ajoutes par le chantier de durcissement retroactif
    # qui leve les stubs RG-SAL-3 "sur stock"/"a acheter" (`stocks`/`purchase`
    # n'existaient pas encore quand `sales` a ete construit, cf. plan) :
    # `services.procurement.qualify_and_process_order` consomme desormais
    # `apps.stocks.services.public.check_and_reserve_stock` et
    # `apps.purchase.services.public.create_requisition_line_from_source` —
    # jamais `apps.stocks.models`/`apps.purchase.models`.
    # "reporting" ajoute par le chantier §5.11 (REP4) : `services.
    # reports_registration._adapter_delivery_note_pdf` consomme `apps.
    # reporting.services.public.render_and_archive` pour l'archivage RPT-10
    # de SAL-BL — jamais `apps.reporting.models`.
    dependencies=(
        "core",
        "partners",
        "catalog",
        "crm",
        "mrp",
        "accounting",
        "stocks",
        "purchase",
        "reporting",
    ),
    verbose_name="Ventes",
)
