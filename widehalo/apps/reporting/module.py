from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="reporting",
    # Dependance declaree = "core" UNIQUEMENT (§5.11, decision de conception
    # actee au cadrage) : le moteur de rapports enveloppe les fonctions
    # `services/reports.py` DEJA construites par les 9 modules metier via un
    # registre partage (`apps.core.services.reports_registry`, meme patron
    # que `apps.core.events`) — chaque module s'auto-enregistre depuis son
    # propre `apps.py::ready()`. `reporting` n'importe donc jamais
    # `apps.accounting.services.reports`/`apps.payroll.services.pdf`/etc.
    # directement, seulement le registre (qui vit dans `core`).
    dependencies=("core",),
    verbose_name="Rapports",
)
