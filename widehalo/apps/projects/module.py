from apps.core.module import ModuleSpec

# Module `projects` (Gestion de projets, PJ1-PJ15, cf. plan). Dependances
# DECLAREES par anticipation du sous-sequencement complet — `partners`
# (client), `accounting` (facturation multi-modes, PJ5) et `strategy`
# (liaison KPI, PJ13) sont annoncees des PJ1 dans la section "Sous-
# sequencement" du plan, meme si AUCUNE n'est encore reellement consommee
# a ce stade (`client_partner_id` et `linked_objective_id` restent de
# simples UUID sur `PrjProject`, jamais une FK ni un appel a
# `services.public` — cf. docstring de `models.py`). Cette declaration
# precoce est sans consequence sur le garde-fou de couplage
# (`tests/architecture/test_module_boundaries.py::
# test_declared_dependencies_match_module_spec` n'echoue QUE sur une
# dependance UTILISEE mais non declaree, jamais l'inverse) et evite de
# devoir retoucher ce fichier a chaque etape PJ2-PJ15 qui cablera l'un de
# ces gaps.
MODULE = ModuleSpec(
    name="projects",
    dependencies=("core", "partners", "accounting", "strategy"),
    verbose_name="Gestion de projets",
)
