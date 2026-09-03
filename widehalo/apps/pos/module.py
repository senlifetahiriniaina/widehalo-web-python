from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="pos",
    # "catalog" : le POS n'a jamais de second catalogue ni de seconde grille
    # de prix (cahier Phase 1 §13.5, regle de gestion) — il consomme
    # `catalog.services.public.get_variant_price`/`is_variant_sellable` et
    # le nouveau gap `search_sellable_variants`, jamais `apps.catalog.models`.
    # "partners" : identification optionnelle du client (ticket anonyme
    # autorise, facture nominative exige un tiers identifie) via le nouveau
    # gap `search_partners`/`get_partner_display_name` — jamais
    # `apps.partners.models`.
    # "stocks" : sortie de stock a la vente (POS distribution) et retour en
    # stock sur avoir, via les nouveaux gaps `sell_from_stock`/
    # `receive_pos_return` — jamais `apps.stocks.models`. Volontairement
    # SANS reservation prealable (a la difference de la chaine
    # commande->livraison de `sales`) : le POS encaisse et sort le stock en
    # un seul geste synchrone (cf. docstring de `sell_from_stock`).
    # "accounting" : cloture de session -> ecriture comptable consolidee par
    # moyen de paiement (POS-7) via le nouveau gap
    # `create_pos_session_closing_entry_from_source`, et resolution du taux
    # de TVA de vente via `get_default_sale_tax` — jamais `apps.accounting.
    # models`.
    # PAS de dependance vers "sales" : le POS est un canal de vente autonome
    # (cahier §13.5, "Deux usages... avec le meme catalogue et la meme
    # tarification que Sales" — catalogue/tarification vivent dans
    # `catalog`, jamais dans `sales` lui-meme), jamais une dependance a la
    # chaine devis/commande de `sales`.
    dependencies=("core", "catalog", "partners", "stocks", "accounting"),
    verbose_name="Point de vente",
)
