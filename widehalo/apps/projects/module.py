from apps.core.module import ModuleSpec

# Module `projects` (Gestion de projets, PJ1-PJ15, cf. plan). Dependances
# DECLAREES par anticipation du sous-sequencement complet des PJ1 —
# `partners` (client) et `accounting` (facturation multi-modes, PJ5)
# restent a ce stade NON consommees (`client_partner_id` reste un simple
# UUID sur `PrjProject`, jamais une FK ni un appel a `services.public` —
# cf. docstring de `models.py`). `strategy` (liaison KPI) a ete cablee a
# PJ13 : `linked_objective_id` reste un simple UUID (jamais une FK, regle
# de couplage n°1 inchangee) mais `services/public.py::
# get_linked_objective_summary` appelle desormais reellement `strategy.
# services.public.get_objective_summary`. Cette declaration precoce est
# sans consequence sur le garde-fou de couplage (`tests/architecture/
# test_module_boundaries.py::test_declared_dependencies_match_module_spec`
# n'echoue QUE sur une dependance UTILISEE mais non declaree, jamais
# l'inverse) et evite de devoir retoucher ce fichier a chaque etape
# PJ2-PJ15 qui cablera l'un de ces gaps.
MODULE = ModuleSpec(
    name="projects",
    dependencies=("core", "partners", "accounting", "strategy"),
    verbose_name="Gestion de projets",
)
