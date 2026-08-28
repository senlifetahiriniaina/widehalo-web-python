from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="purchase",
    # "accounting" ajoute par PU6 (RG-PUR-6/RG-PUR-7/PUR-BUD1, cf. plan) :
    # premiere fois que `purchase` consomme `accounting.services.public`
    # (facture fournisseur 3 voies, lot de couts d'importation, ecart
    # budgetaire par axe analytique) — jamais `apps.accounting.models`.
    # "mrp" ajoute par PU7 (RG-PUR-8, cf. plan) : mutualisation de
    # l'evaluation fournisseur (MRP-QQCD1) via `mrp.services.public.
    # record_supplier_evaluation`/`get_supplier_score`/
    # `list_supplier_evaluations` — jamais `apps.mrp.models`.
    # "stocks" ajoute par le chantier de durcissement retroactif qui leve
    # le stub RG-PUR-3 (`stocks` n'existait pas encore quand `purchase` a
    # ete construit, cf. plan) : `services.reordering.run_reordering`
    # consomme desormais `apps.stocks.services.public.get_available_stock_qty`
    # — jamais `apps.stocks.models`.
    dependencies=("core", "partners", "catalog", "accounting", "mrp", "stocks"),
    verbose_name="Achats",
)
