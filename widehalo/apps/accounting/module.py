from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="accounting",
    # "stocks" ajoute par le chantier de durcissement retroactif qui leve
    # le stub A17/ACC-IMP (`stocks` n'existait pas encore quand `accounting`
    # a ete construit, cf. plan) : `services.landed_costs.finalize_batch`
    # consomme desormais `apps.stocks.services.public.
    # apply_landed_cost_to_valuation` — jamais `apps.stocks.models`.
    dependencies=("core", "partners", "stocks"),
    verbose_name="Comptabilite",
)
