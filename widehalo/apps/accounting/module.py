from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="accounting", dependencies=("core", "partners"), verbose_name="Comptabilite"
)
