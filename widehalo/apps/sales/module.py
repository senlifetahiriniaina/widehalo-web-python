from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="sales",
    dependencies=("core", "partners", "catalog", "crm", "mrp", "accounting"),
    verbose_name="Ventes",
)
