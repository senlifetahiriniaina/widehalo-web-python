from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="patronage",
    dependencies=("core", "catalog", "mrp"),
    verbose_name="Patrons et gradation",
)
