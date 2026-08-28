from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="stocks",
    # ST1 (cf. plan) ne consomme que `core.User` (FK manager de
    # `StkWarehouse`, appartient au socle) — aucun import de
    # `catalog.services.public` a ce stade malgre la dependance prevue au
    # sous-sequencement complet (ST2+ : conversion m/kg RG-STK-5). Ne PAS
    # declarer "catalog" tant qu'aucune fonction n'est reellement importee
    # (discipline "ne declarer que ce qui est importe", identique a tous
    # les modules precedents) — a ajouter en ST2/ST3 quand
    # `catalog.services.public.get_variant_conversion`/equivalent sera
    # effectivement utilise.
    dependencies=("core",),
    verbose_name="Stocks",
)
