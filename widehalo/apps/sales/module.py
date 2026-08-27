from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="sales",
    dependencies=("core", "partners", "catalog", "crm"),
    verbose_name="Ventes",
)
