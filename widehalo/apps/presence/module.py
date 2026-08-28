from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="presence",
    # "mrp" consommee via `services.public` uniquement, des PR4 (RG-PRS-8,
    # rapprochement CRA) — jamais un import de `apps.mrp.models`.
    dependencies=("core", "mrp"),
    verbose_name="Présence et absences",
)
