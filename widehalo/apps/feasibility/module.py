from apps.core.module import ModuleSpec

# Chantier « etudes de faisabilite » (FEA1-3, cf. plan section « Etudes de
# faisabilite, veille prix fournisseurs, capacite 90j, risques
# operationnels, qualite/certification, refonte UI/UX »). Objectif metier :
# simuler le cout/prix/marge d'un produit ou d'un ensemble de produits SANS
# qu'un client/prospect reel n'existe (`crm` n'est donc PAS une dependance —
# une etude de faisabilite est explicitement une hypothese hors pipeline
# commercial reel).
#
# Dependances declarees, toutes via `services.public` UNIQUEMENT (regle de
# couplage n1, verifiee par `tests/architecture/test_module_boundaries.py`) :
# - `catalog` : `get_variant_price()` si une variante reelle existe deja
#   pour l'etude (prix hypothetique saisi manuellement sinon) ;
# - `mrp` : `simulate_bom_cost()` (gap ajoute par ce chantier) si une BOM
#   reelle existe pour chiffrer le cout matiere/facon/frais generaux ;
#   sinon l'appelant retombe sur un `cost_breakdown` saisi manuellement.
MODULE = ModuleSpec(
    name="feasibility",
    dependencies=("core", "catalog", "mrp"),
    verbose_name="Etudes de faisabilite",
)
