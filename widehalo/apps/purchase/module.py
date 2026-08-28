from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="purchase",
    # "accounting" ajoute par PU6 (RG-PUR-6/RG-PUR-7/PUR-BUD1, cf. plan) :
    # premiere fois que `purchase` consomme `accounting.services.public`
    # (facture fournisseur 3 voies, lot de couts d'importation, ecart
    # budgetaire par axe analytique) — jamais `apps.accounting.models`.
    dependencies=("core", "partners", "catalog", "accounting"),
    verbose_name="Achats",
)
