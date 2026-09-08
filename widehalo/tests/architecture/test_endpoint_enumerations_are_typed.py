"""Garde-fou bloquant — T1 : un parametre d'endpoint a valeurs FERMEES se
declare par son type, jamais par `str`.

**Le defaut mesure.** 41 endpoints de rapport declaraient `format: str`.
Django-ninja acceptait donc n'importe quelle chaine, la passait au
`rows_to_bytes` du module, qui levait `ValueError` — ou, quand la valeur
atteignait le dictionnaire de types MIME, un `KeyError` sec. Dans les deux
cas : **500**. Un utilisateur demandant `?format=pdf` sur un rapport qui ne
fait pas de PDF obtenait « une erreur inattendue est survenue » alors que sa
demande etait simplement hors du menu.

Le critere de la Phase 4 est explicite sur ce point : le systeme tiers
« ne lit aucune documentation contextuelle, ne devine rien, ne pardonne
rien » et attend « des codes d'erreur explicites ». Un 500 sur un parametre
hors enumeration n'en est pas un.

**Pourquoi une garde et pas seulement une correction.** Corriger les 41
laisse le 42e revenir : le prochain endpoint de rapport se copiera-collera
depuis un voisin. La garde est ce qui rend la correction durable, et elle
tient en une ligne d'analyse statique — le meme patron que
`test_endpoint_permissions.py`, qui refuse un endpoint sans decorateur de
permission.

Ne JAMAIS ajouter d'exception ici sans motif ecrit : un parametre a valeurs
fermees typé `str` est un 500 en attente, pas une preference de style.
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

#: Les noms de parametre dont le jeu de valeurs est FERME dans ce depot, et
#: le type qui l'exprime. Fermer le jeu par le type fait rejeter la valeur
#: par la validation de schema de django-ninja — donc 422 en nommant le
#: parametre, AVANT que le moindre service ne tourne.
PARAMETRES_A_JEU_FERME: dict[str, str] = {
    "format": "ReportFormat (apps.core.report_formats) ou un Literal explicite",
}


def _endpoint_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    """Les fonctions portant un decorateur `@router.<verbe>(...)`.

    On ne regarde que les vues d'API : un service peut legitimement
    recevoir un `format: str` et lever — c'est ce qu'il fait, et c'est bien
    (`rows_to_bytes` reste defensif pour ses appelants directs). Ce qui est
    interdit, c'est qu'une valeur non filtree ARRIVE jusqu'a lui depuis une
    requete HTTP."""
    trouvees = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorateur in node.decorator_list:
            cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
            if (
                isinstance(cible, ast.Attribute)
                and isinstance(cible.value, ast.Name)
                and cible.value.id == "router"
            ):
                trouvees.append(node)
                break
    return trouvees


def _annotation_source(annotation: ast.expr | None) -> str:
    return "" if annotation is None else ast.unparse(annotation)


def test_no_endpoint_declares_a_closed_vocabulary_as_a_bare_string() -> None:
    violations: list[str] = []
    for chemin in sorted(APPS_DIR.rglob("api*.py")):
        if "/tests/" in str(chemin):
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for fonction in _endpoint_functions(arbre):
            arguments = [*fonction.args.args, *fonction.args.kwonlyargs]
            for argument in arguments:
                attendu = PARAMETRES_A_JEU_FERME.get(argument.arg)
                if attendu is None:
                    continue
                annotation = _annotation_source(argument.annotation)
                if annotation in {"str", "str | None", "Optional[str]"}:
                    violations.append(
                        f"{chemin.relative_to(APPS_DIR.parent)}:{fonction.lineno} "
                        f"{fonction.name}({argument.arg}: {annotation}) — attendu : {attendu}"
                    )
    assert not violations, (
        "Parametre a jeu ferme declare `str` — django-ninja laissera passer "
        "n'importe quelle valeur et l'endpoint rendra 500 au lieu de 422 :\n"
        + "\n".join(violations)
    )


def test_the_guard_detects_a_bare_string_parameter() -> None:
    """Auto-test du garde-fou : sans lui, il pourrait ne rien regarder du
    tout et rester vert pour toujours."""
    source = "@router.get('/x')\ndef x_endpoint(request, format: str = 'json'):\n    return {}\n"
    arbre = ast.parse(source)
    fonctions = _endpoint_functions(arbre)
    assert len(fonctions) == 1
    argument = fonctions[0].args.args[1]
    assert argument.arg in PARAMETRES_A_JEU_FERME
    assert _annotation_source(argument.annotation) == "str"


def test_no_report_screen_reads_the_format_parameter_raw() -> None:
    """L'autre surface, et le meme 500.

    Les vues Django d'ecran n'ont pas de validation de schema pour les
    proteger : elles lisaient `request.GET.get("format", "json")` et
    passaient la valeur telle quelle a `_CONTENT_TYPES[format]` — un
    `KeyError`, donc un 500, pour un utilisateur qui a tape `?format=pdf`
    dans la barre d'adresse. `apps.core.report_formats.parse_report_format`
    est le seul chemin autorise : il rend 400 avec le menu des formats.

    Garde textuelle et non AST, delibérement : ce qu'on interdit est une
    LECTURE BRUTE, pas une forme syntaxique — et la lecture brute s'ecrit
    d'une seule facon dans ce depot."""
    violations: list[str] = []
    for chemin in sorted(APPS_DIR.glob("*/views_reports.py")):
        source = chemin.read_text(encoding="utf-8")
        for numero, ligne in enumerate(source.splitlines(), start=1):
            if 'GET.get("format"' in ligne and "parse_report_format" not in ligne:
                violations.append(
                    f"{chemin.relative_to(APPS_DIR.parent)}:{numero} — {ligne.strip()}"
                )
    assert not violations, (
        "Lecture brute du parametre `format` sur un ecran de rapport : la "
        "valeur atteindra le dictionnaire de types MIME et l'ecran rendra "
        "500 au lieu de 400.\nUtiliser "
        "`apps.core.report_formats.parse_report_format` :\n" + "\n".join(violations)
    )
