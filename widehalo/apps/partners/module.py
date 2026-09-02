from apps.core.module import ModuleSpec

# "accounting" ajoute par le chantier "fiche partenaire a onglets par role"
# (PT3) : `services/accounts.py` consomme
# `apps.accounting.services.public.list_accounts`/
# `assign_partner_role_account`/`list_partner_role_accounts` — jamais un
# import de `apps.accounting.models`.
#
# "catalog"/"purchase" ajoutes par PT5 du meme chantier : l'onglet
# "Fournisseur (achat)" consomme
# `apps.catalog.services.public.list_supplier_products` et
# `apps.purchase.services.public.list_orders_for_partner` — jamais un
# import de `apps.catalog.models`/`apps.purchase.models`.
#
# "sales" ajoute par PT6 du meme chantier : l'onglet "Client" consomme
# `apps.sales.services.public.list_quotations_for_partner`/
# `list_orders_for_partner` — jamais un import de `apps.sales.models`.
#
# "mrp" ajoute par PT7 du meme chantier : l'onglet "Fournisseur atelier
# (sous-traitant)" consomme
# `apps.mrp.services.public.list_subcontract_orders_for_partner`/
# `get_supplier_score`/`list_supplier_evaluations` — jamais un import de
# `apps.mrp.models`.
#
# "logistics" ajoute par PT8 du meme chantier : l'onglet "Transporteur"
# consomme `apps.logistics.services.public.list_shipments_for_partner` —
# jamais un import de `apps.logistics.models`.
MODULE = ModuleSpec(
    name="partners",
    dependencies=(
        "core",
        "chat",
        "accounting",
        "catalog",
        "purchase",
        "sales",
        "mrp",
        "logistics",
    ),
    verbose_name="Partenaires",
)
