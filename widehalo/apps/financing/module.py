from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="financing",
    dependencies=("core", "accounting", "sales", "purchase", "logistics"),
    verbose_name="Financement bancaire PME",
)
