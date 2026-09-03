from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="mrp",
    # "stocks" ajoute par A2 (L4 Agro, cf. docs/planning/
    # 2026-refonte-ux-sprints.md §5) : premiere fois que `mrp` consomme
    # `stocks.services.public.receive_production_output`/
    # `record_lot_genealogy`/`lot_genealogy_tree`/`list_locations`
    # (`services/transformation.py`) — jamais `apps.stocks.models`.
    dependencies=("core", "catalog", "stocks"),
    verbose_name="Production",
)
