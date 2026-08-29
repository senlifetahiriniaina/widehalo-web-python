from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="strategy",
    dependencies=("core", "presence", "sales", "payroll", "accounting", "mrp"),
    verbose_name="Strategie et pilotage",
)
