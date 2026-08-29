from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="automation",
    # Dependance UNIQUEMENT sur `core` (cf. plan, cadrage du Studio de
    # workflow visuel) — jamais un import direct des modeles/services.public
    # d'un autre module metier. Chaque module qui souhaite exposer une
    # action au studio s'auto-enregistre dans `core.services.
    # automation_registry` depuis son PROPRE `apps.py::ready()` ; le
    # moteur d'execution (`services/engine.py`) n'appelle que des
    # fonctions deja resolues via ce registre, jamais un import direct.
    dependencies=("core",),
    verbose_name="Studio de workflow visuel",
)
