from apps.core.module import ModuleSpec

# Chantier Qualite/HACCP (cahier Phase 3 §3.5) — application dediee, decidee
# avec l'utilisateur plutot qu'une fusion dans `apps.stocks` (decision D2,
# cf. `docs/planning/2026-09-adr-qualite-haccp-app-dediee.md`, l'ADR complet
# qui justifie ce choix et ce qu'il laisse explicitement en suspens pour le
# Bloc D).
#
# "stocks" ajoute par D1 (Bloc D) : premiere consommation cross-app reelle
# de `quality` — `services/measurements.py::record_measurement` appelle
# `stocks.services.public.set_quality_state` pour bloquer physiquement un
# lot dont une mesure sort des limites critiques (QUA-1/2/3). `quality`
# n'importe jamais `apps.stocks.models` — seulement sa surface
# `services.public`, identite de lot opaque `(tenant, variant_id, name)`.
MODULE = ModuleSpec(
    name="quality",
    dependencies=("core", "stocks"),
    verbose_name="Qualite et HACCP",
)
