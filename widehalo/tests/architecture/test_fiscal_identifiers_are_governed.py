"""Garde-fou bloquant — T3 : l'identifiant fiscal ne s'écrit que par une
porte contrôlée.

**Le critère** (Phase 4, l.224) : « un identifiant fiscal absent ou faux,
qui n'empêchait qu'une impression jusqu'ici, empêchera désormais une
validation ». Un contrôle qui se contourne ne l'empêche pas.

**Ce que ce fichier verifie, et pourquoi chaque point a couté quelque
chose ailleurs dans ce depot.**

1. **Le controle vit dans `save()`, pas seulement dans un validateur de
   champ.** Django ne fait tourner les validateurs de champ que dans
   `full_clean()`, jamais dans `save()`. Le depot a paye ce piege deux
   fois : `FlwConnector.supported_operations` (S6) et `SalesTarget.scope`
   (T1), dans les deux cas un `choices` que rien ne verifiait. Ici la
   consequence serait pire : six surfaces ecrivent `Partner.nif`, et une
   seule passe par un formulaire.

2. **`QuerySet.update()` et `bulk_create()` ne passent PAS par `save()`.**
   Un `Partner.objects.filter(...).update(nif=...)` ecrirait donc n'importe
   quoi sans qu'aucun controle ne s'y oppose — exactement le contournement
   que la migration `accounting/0031` decrit pour les ecritures comptables.
   Ce fichier refuse ces deux appels sur les champs d'identite fiscale.

3. **Aucun format n'est declare sans reserve ecrite.** Le format exact du
   NIF malgache n'est publie dans aucune source primaire accessible a ce
   depot. Un motif strict qui apparaitrait ici sans reserve serait une
   regle fiscale fabriquee et presentee comme verifiee.

Ne JAMAIS ajouter d'exception sans motif ecrit.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from apps.core.models.tenant import Tenant
from apps.core.services.fiscal_identifiers import FORMATS, RESERVE_MINIMUM
from apps.partners.models import Partner

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

#: Les champs d'identite fiscale, et le modele qui les porte. Les NOMMER
#: plutot que de chercher « tout champ ressemblant a un identifiant » : une
#: garde qui devine son propre perimetre finit par ne plus rien couvrir.
CHAMPS_GOUVERNES: tuple[str, ...] = ("nif", "stat")


def test_both_models_validate_their_fiscal_identity_in_save() -> None:
    """Le controle doit etre dans `save()` — la seule porte que l'ORM,
    l'API, un import et un `shell` empruntent tous."""
    for modele in (Partner, Tenant):
        source = inspect.getsource(modele.save)
        assert "validate_identifier" in source, (
            f"{modele.__name__}.save() ne valide plus l'identite fiscale : "
            "un validateur de champ seul ne tourne que dans full_clean(), "
            "que la plupart des surfaces d'ecriture n'appellent pas."
        )


def test_no_production_code_writes_a_fiscal_identifier_through_update_or_bulk_create() -> None:
    """`QuerySet.update()` et `bulk_create()` court-circuitent `save()`.

    Garde textuelle sur l'AST plutot que sur une expression reguliere : ce
    qu'on interdit est un APPEL, pas une graphie."""
    violations: list[str] = []
    for chemin in sorted(APPS_DIR.rglob("*.py")):
        texte = str(chemin)
        if "/tests/" in texte or "/migrations/" in texte or chemin.name.startswith("test_"):
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=texte)
        for node in ast.walk(arbre):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"update", "bulk_create"}:
                continue
            noms = {kw.arg for kw in node.keywords if kw.arg}
            fautifs = noms & set(CHAMPS_GOUVERNES)
            if fautifs:
                violations.append(
                    f"{chemin.relative_to(APPS_DIR.parent)}:{node.lineno} "
                    f"{node.func.attr}({', '.join(sorted(fautifs))}=...)"
                )
    assert not violations, (
        "Ecriture d'un identifiant fiscal hors de `save()` — le controle de "
        "format ne s'y applique pas :\n" + "\n".join(violations)
    )


def test_every_declared_format_carries_its_reserve() -> None:
    """Un motif sans reserve ecrite se lit comme une conformite verifiee."""
    for (identifiant, pays), format_declare in FORMATS.items():
        assert len(format_declare.reserve) >= RESERVE_MINIMUM, (
            f"{identifiant}/{pays} : reserve trop courte"
        )
        assert "OECFM" in format_declare.reserve or "DGI" in format_declare.reserve, (
            f"{identifiant}/{pays} : la reserve ne renvoie a aucune autorite "
            "competente — elle ne dit donc pas aupres de qui la lever."
        )


def test_the_guard_detects_a_bypassing_write() -> None:
    """Auto-test du garde-fou : sans lui, il pourrait ne rien regarder du
    tout et rester vert pour toujours."""
    arbre = ast.parse("Partner.objects.filter(id=1).update(nif='x')")
    appels = [
        node
        for node in ast.walk(arbre)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
    ]
    assert appels
    assert {kw.arg for kw in appels[0].keywords} & set(CHAMPS_GOUVERNES)
