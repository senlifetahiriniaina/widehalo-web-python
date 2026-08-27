from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="purchase",
    dependencies=("core", "partners", "catalog"),
    verbose_name="Achats",
)
