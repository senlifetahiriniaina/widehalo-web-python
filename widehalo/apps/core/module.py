"""Contrat de dependances declaratives entre apps du modulith.

Chaque app metier doit exposer, dans son propre `module.py`, un objet
`MODULE = ModuleSpec(name=..., dependencies=(...))`. `tests/architecture/
test_module_boundaries.py` verifie que les dependances declarees ici
correspondent aux imports reellement observes vers `services.public`
d'autres apps.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    verbose_name: str = ""


MODULE = ModuleSpec(name="core", dependencies=(), verbose_name="Socle")
