from apps.core.module import ModuleSpec

# Module `projects` (Gestion de projets, PJ1-PJ15, chantier TERMINE — cf.
# plan). Dependances DECLAREES des PJ1, par anticipation du
# sous-sequencement complet :
# - `accounting` (facturation multi-modes) a ete cablee a PJ5 :
#   `services/billing.py` appelle reellement `accounting.services.public.
#   create_customer_invoice_from_source` — jamais de FK Django cross-app,
#   uniquement ce point d'entree `services.public`.
# - `strategy` (liaison KPI) a ete cablee a PJ13 : `linked_objective_id`
#   reste un simple UUID sur `PrjProject` (jamais une FK, regle de
#   couplage n°1 inchangee) mais `services/public.py::
#   get_linked_objective_summary` appelle desormais reellement `strategy.
#   services.public.get_objective_summary`.
# - `partners` reste NON consommee au terme du chantier (`client_partner_id`
#   reste un simple UUID sur `PrjProject`, jamais une FK ni un appel a
#   `partners.services.public` — cf. docstring de `models.py`) : aucun
#   ecran de ce module n'a exige de resoudre ce partenaire au-dela de sa
#   simple presence/absence (verifiee par `services/billing.py` avant
#   toute facturation). Gap connu, disclosed pour le rapport de cloture
#   PJ15 plutot qu'un cablage invente sans besoin fonctionnel reel derriere.
# Cette declaration precoce reste sans consequence sur le garde-fou de
# couplage (`tests/architecture/test_module_boundaries.py::
# test_declared_dependencies_match_module_spec` n'echoue QUE sur une
# dependance UTILISEE mais non declaree, jamais l'inverse).
MODULE = ModuleSpec(
    name="projects",
    dependencies=("core", "partners", "accounting", "strategy"),
    verbose_name="Gestion de projets",
)
