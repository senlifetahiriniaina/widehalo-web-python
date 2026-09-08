"""Garde-fou bloquant — T4bis : un identifiant se déclare `UUID`, jamais `str`.

**Le défaut mesuré, et pourquoi il est revenu.** Le lot T1 a fermé la même
classe sur le paramètre `format` — 41 endpoints qui rendaient 500 sur une
valeur hors menu — et il l'a écrit noir sur blanc : « corriger les 41
laisse le 42ᵉ revenir : le prochain endpoint se copiera-collera depuis un
voisin ». La mesure faite après T4 lui a donné raison de la pire façon.
Mesure par AST sur l'arbre entier :

    63 appels `uuid.UUID()` sur une valeur d'entrée non typée
    164 champs de schéma `*_id` non typés `UUID`, sur 17 modules

`uuid.UUID` lève `ValueError` sur une chaîne mal formée. Aucun
gestionnaire de ce dépôt ne rattrape `ValueError` : elle tombe dans le
gestionnaire générique (`apps.core.errors.on_unhandled_exception`), qui
rend **500**. Un presse-papier qui tronque un identifiant suffisait.

Le critère de la Phase 4 ne laisse pas d'échappatoire : le système tiers
« ne lit aucune documentation contextuelle, ne devine rien, ne pardonne
rien » et attend « des codes d'erreur explicites ». Un 500 sur un
identifiant malformé n'en est pas un.

**Le TYPE, pas une conversion défensive.** Déclarer `partner_id: UUID`
fait rejeter la valeur par la validation de schéma de django-ninja — 422
avec le nom du champ, AVANT que le moindre service ne tourne, et visible
dans l'OpenAPI, ce qui est précisément ce dont un intégrateur a besoin.
Une conversion `uuid.UUID(payload.x)` enveloppée dans un `try` aurait dû
être écrite 164 fois et oubliée à la 165ᵉ.

**Pourquoi les deux gardes ci-dessous et pas une seule.** La première
refuse la déclaration `str` ; la seconde refuse la conversion manuelle qui
la RENDRAIT INVISIBLE. Un champ correctement typé `UUID` dont l'appelant
fait encore `uuid.UUID(payload.x)` est du code mort — mais du code mort
qui masquerait un retour à `str` : la première garde resterait verte alors
que le défaut serait revenu. Les deux ensemble ferment la porte et la
fenêtre.

Ne JAMAIS ajouter d'exemption sans motif écrit : un identifiant déclaré
`str` est un 500 en attente, pas une préférence de style.
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

#: Les suffixes qui désignent un identifiant dans ce dépôt. Une convention
#: de NOMMAGE plutôt qu'une liste de champs : la liste serait à tenir à
#: jour, la convention se vérifie toute seule.
SUFFIXES_IDENTIFIANT = ("_id", "_ids", "_uuid")

#: Les champs qui portent un de ces suffixes SANS être un UUID de ce
#: dépôt. Chaque entrée est une décision, avec son motif — jamais une
#: commodité pour faire taire la garde.
EXEMPTIONS: dict[str, str] = {
    # `apps.automation` : un pas de flux est désigné par sa clef dans le
    # canevas visuel, une chaîne libre choisie par l'utilisateur qui
    # dessine le flux — pas un UUID. La valeur va dans
    # `get_object_or_404(flow.steps, id=...)`, qui rend 422 par le
    # gestionnaire de `ValidationError` (T1) et jamais 500.
    "ConditionStepIn.next_step_id": "clef d'étape du canevas visuel, pas un UUID",
    "ConditionStepIn.next_step_on_false_id": "clef d'étape du canevas visuel, pas un UUID",
    "ActionStepIn.next_step_id": "clef d'étape du canevas visuel, pas un UUID",
    # `django.contrib.contenttypes.ContentType` a une clef primaire ENTIÈRE :
    # c'est une table de Django, pas un `BaseModel` de ce dépôt, et elle n'a
    # jamais eu d'`UUIDField`. La typer `UUID` refuserait toute valeur valide.
    "InspectionIn.content_type_id": "clef primaire entière de django ContentType, jamais un UUID",
}


def _schema_classes(tree: ast.AST) -> list[ast.ClassDef]:
    """Les classes qui héritent de `Schema` (django-ninja).

    Un modèle Django ou une dataclasse interne peut légitimement porter un
    `*_id` textuel : ce qui est interdit, c'est qu'une valeur non filtrée
    ARRIVE depuis une requête HTTP."""
    trouvees = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            for base in node.bases
        }
        if "Schema" in bases:
            trouvees.append(node)
    return trouvees


def _fichiers_de_surface() -> list[Path]:
    """`api*.py` et `schemas.py` — les deux endroits où un schéma se déclare.

    Ne regarder que `api.py` était le défaut du premier passage de ce
    chantier : `apps.pos` déclare les siens dans `schemas.py`, et douze
    champs sont passés entre les mailles."""
    fichiers = [*APPS_DIR.rglob("api*.py"), *APPS_DIR.rglob("schemas.py")]
    return sorted(f for f in fichiers if "/tests/" not in str(f))


def test_no_schema_declares_an_identifier_as_a_bare_string() -> None:
    violations: list[str] = []
    for chemin in _fichiers_de_surface():
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for classe in _schema_classes(arbre):
            for stmt in classe.body:
                if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                    continue
                nom = stmt.target.id
                if not nom.endswith(SUFFIXES_IDENTIFIANT):
                    continue
                if f"{classe.name}.{nom}" in EXEMPTIONS:
                    continue
                annotation = ast.unparse(stmt.annotation)
                if "UUID" in annotation:
                    continue
                violations.append(
                    f"{chemin.relative_to(APPS_DIR.parent)}:{stmt.lineno} "
                    f"{classe.name}.{nom}: {annotation}"
                )
    assert not violations, (
        "Identifiant déclaré `str` dans un schéma d'entrée — django-ninja "
        "laissera passer n'importe quelle valeur, et `uuid.UUID()` rendra 500 "
        "au lieu de 422 :\n" + "\n".join(violations)
    )


def test_no_endpoint_converts_an_identifier_by_hand() -> None:
    """La conversion manuelle est interdite parce qu'elle MASQUE le retypage.

    Un `uuid.UUID(payload.x)` sur un champ correctement typé est du code
    mort ; le jour où quelqu'un remet le champ en `str`, la garde ci-dessus
    resterait verte et le 500 reviendrait sans bruit. Les deux gardes
    ensemble ferment la porte et la fenêtre."""
    violations: list[str] = []
    for chemin in _fichiers_de_surface():
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for node in ast.walk(arbre):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            cible = node.func
            est_uuid = (isinstance(cible, ast.Attribute) and cible.attr == "UUID") or (
                isinstance(cible, ast.Name) and cible.id == "UUID"
            )
            if not est_uuid:
                continue
            argument = ast.unparse(node.args[0])
            if argument.startswith(("payload.", "line.", "spec.")):
                violations.append(
                    f"{chemin.relative_to(APPS_DIR.parent)}:{node.lineno} UUID({argument})"
                )
    assert not violations, (
        "Conversion manuelle d'un identifiant de schéma : le champ doit être "
        "déclaré `UUID`, et la conversion supprimée — la garder masquerait un "
        "retour à `str` :\n" + "\n".join(violations)
    )


def test_no_screen_view_converts_a_request_value_by_hand() -> None:
    """La troisième surface : les vues d'écran, qui n'ont pas de schéma.

    `apps.core.identifiers.parse_uuid` est le seul chemin autorisé — il
    rend 400 en NOMMANT le champ, là où `uuid.UUID(request.POST.get(...))`
    rend 500. Même répartition que le lot T1 entre `ReportFormat` (le type,
    côté API) et `parse_report_format` (la fonction, côté écran)."""
    violations: list[str] = []
    for chemin in sorted(APPS_DIR.rglob("views*.py")):
        if "/tests/" in str(chemin):
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for node in ast.walk(arbre):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            cible = node.func
            est_uuid = (isinstance(cible, ast.Attribute) and cible.attr == "UUID") or (
                isinstance(cible, ast.Name) and cible.id == "UUID"
            )
            if not est_uuid:
                continue
            argument = ast.unparse(node.args[0])
            if "request." in argument or "post.get" in argument.lower():
                violations.append(
                    f"{chemin.relative_to(APPS_DIR.parent)}:{node.lineno} UUID({argument})"
                )
    assert not violations, (
        "Conversion brute d'une valeur de requête dans une vue d'écran : "
        "`uuid.UUID` lève `ValueError`, que rien ne rattrape, donc 500.\n"
        "Utiliser `apps.core.identifiers.parse_uuid` :\n" + "\n".join(violations)
    )


def test_the_guard_detects_a_bare_identifier() -> None:
    """Auto-test du garde-fou : sans lui, il pourrait ne rien regarder du
    tout et rester vert pour toujours."""
    source = "class FactureIn(Schema):\n    partner_id: str | None = None\n"
    arbre = ast.parse(source)
    classes = _schema_classes(arbre)
    assert len(classes) == 1
    champ = classes[0].body[0]
    assert isinstance(champ, ast.AnnAssign)
    assert isinstance(champ.target, ast.Name)
    assert champ.target.id.endswith(SUFFIXES_IDENTIFIANT)
    assert "UUID" not in ast.unparse(champ.annotation)


def test_every_exemption_carries_a_written_motive() -> None:
    """Une exemption sans motif écrit se lit comme une règle, pas comme une
    dérogation — et personne ne la retire jamais."""
    for cle, motif in EXEMPTIONS.items():
        assert len(motif) >= 30, f"{cle} : motif trop court pour dire quoi que ce soit"
