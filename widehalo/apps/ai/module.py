from apps.core.module import ModuleSpec

# Module `ai` (intelligence artificielle transversale), porte depuis
# l'ancienne version WideHalo (Laravel), adapte a ce socle Django — cf. plan
# section « Module `ai` (Intelligence artificielle transversale) ». Assistant
# contextuel par page, detection d'anomalies cross-modules, recherche en
# langage naturel, budget de tokens par tenant, insights proactifs, cache de
# prompts, advisor d'actions, fallback-first.
#
# Dependance declaree : `core` UNIQUEMENT. Inversion de controle
# systematique (meme discipline que `apps.reporting`/`apps.automation`) :
# ce sont les AUTRES modules metier qui s'enregistrent DANS les registres
# generiques exposes par `core` (`ai_context_registry`, `anomaly_registry`)
# via leur propre `apps.py::ready()` — `ai` ne connait et n'importe JAMAIS
# un modele d'un autre module metier.
MODULE = ModuleSpec(
    name="ai",
    dependencies=("core",),
    verbose_name="Intelligence artificielle",
)
