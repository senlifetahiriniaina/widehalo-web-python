"""D-0 — une colonne de liste désigne quelque chose qui existe.

**Le défaut, mesuré.** `/accounting/config/taxes/` déclare
`Column(key="rate_pct", label="Taux (%)")` pour des `AccTax`, **qui n'ont
pas ce champ** — il s'appelle `rate`. Le filtre de rendu a un défaut à
`""` : pas de 500, pas de trace, juste une cellule vide sur chaque ligne
sous un en-tête qui promet un taux. L'en-tête n'est même pas triable, ce
qui rend la colonne inerte de bout en bout.

**Ce que cette garde couvre, et ce qu'elle ne couvre pas.** Elle apparie,
fichier par fichier, une constante `… = [Column(...)]` avec le modèle
interrogé par la vue qui la passe en `columns=`. Elle ne voit donc ni les
colonnes construites dynamiquement, ni celles dont la vue interroge
plusieurs modèles. Son auto-test dit combien de paires elle a formées : si
ce nombre s'effondre, c'est l'instrument qui a cessé de mesurer, pas le
dépôt qui est devenu sain.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from django.apps import apps

pytestmark = pytest.mark.django_db

#: `tests/architecture/<fichier>` : deux parents au-dessus, on est a la
#: racine du projet Django. Une premiere version ajoutait un « widehalo »
#: de trop et retombait sur `tests/` — l'instrument trouvait alors ZERO
#: fichier de vues et la garde passait au vert en ne verifiant rien. C'est
#: le plancher ci-dessous qui l'a dit, pas la relecture.
_RACINE = pathlib.Path(__file__).resolve().parents[2]
assert (_RACINE / "apps").is_dir(), f"Racine de projet introuvable depuis {__file__}"


def _fichiers_de_vues() -> list[pathlib.Path]:
    chemins = list((_RACINE / "apps").rglob("views*.py")) + list(
        (_RACINE / "apps").rglob("views/*.py")
    )
    return [c for c in chemins if "__pycache__" not in str(c) and "/tests/" not in str(c)]


def _paires() -> list[tuple[str, str, list[str], str]]:
    """(fichier, constante, clefs, modele) — ce que l'instrument a apparié."""
    paires: list[tuple[str, str, list[str], str]] = []
    for chemin in _fichiers_de_vues():
        source = chemin.read_text(encoding="utf-8")
        if "Column(" not in source:
            continue
        arbre = ast.parse(source)

        importe: dict[str, str] = {}
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.ImportFrom) and noeud.module and ".models" in noeud.module:
                for alias in noeud.names:
                    importe[alias.asname or alias.name] = noeud.module

        colonnes: dict[str, list[str]] = {}
        for noeud in arbre.body:
            if not isinstance(noeud, ast.Assign) or not isinstance(noeud.value, ast.List):
                continue
            cibles = [t.id for t in noeud.targets if isinstance(t, ast.Name)]
            if not cibles:
                continue
            clefs = [
                mot.value
                for element in noeud.value.elts
                if isinstance(element, ast.Call) and getattr(element.func, "id", "") == "Column"
                for mot in element.args + [kw.value for kw in element.keywords if kw.arg == "key"]
                if isinstance(mot, ast.Constant) and isinstance(mot.value, str)
            ]
            if clefs:
                colonnes[cibles[0]] = clefs

        # **L'appariement se fait AU POINT D'APPEL**, jamais « le premier
        # modèle du fichier ». Une première version prenait le premier
        # `X.objects` rencontré dans la fonction et appariait la liste des
        # récurrences au modèle des commandes — un faux couple, qui aurait
        # produit un faux échec. Le couple juste est écrit dans l'appel :
        # `columns=…` et `queryset=…` y sont voisins.
        #
        # La plupart des vues passent `queryset=<variable>` : on résout
        # alors la variable dans la fonction englobante, ce qui fait passer
        # l'instrument de 17 paires à l'essentiel du dépôt.
        def _racine(expression: ast.expr) -> str | None:
            courant: ast.AST = expression
            while isinstance(courant, ast.Call | ast.Attribute):
                courant = courant.func if isinstance(courant, ast.Call) else courant.value
            return getattr(courant, "id", None)

        for fonction in ast.walk(arbre):
            if not isinstance(fonction, ast.FunctionDef):
                continue
            locales: dict[str, str] = {}
            for noeud in ast.walk(fonction):
                if isinstance(noeud, ast.Assign) and len(noeud.targets) == 1:
                    cible = getattr(noeud.targets[0], "id", None)
                    origine = _racine(noeud.value)
                    if cible and origine and origine in importe:
                        locales.setdefault(cible, origine)

            for appel in ast.walk(fonction):
                if not isinstance(appel, ast.Call):
                    continue
                mots = {kw.arg: kw.value for kw in appel.keywords if kw.arg}
                if "columns" not in mots or "queryset" not in mots:
                    continue
                constante = getattr(mots["columns"], "id", None)
                if constante not in colonnes:
                    continue
                origine = _racine(mots["queryset"])
                modele = origine if origine in importe else locales.get(origine or "")
                if modele not in importe:
                    continue
                paires.append(
                    (str(chemin), constante, colonnes[constante], f"{importe[modele]}.{modele}")
                )
    return paires


def test_the_instrument_still_finds_pairs_to_check() -> None:
    """Sans ce plancher, une garde qui n'apparie plus rien passerait au vert
    en ne vérifiant rien — le motif le plus coûteux de ce dépôt."""
    paires = _paires()
    assert len(paires) >= 35, (
        f"L'instrument n'apparie plus que {len(paires)} listes de colonnes à leur modèle : "
        "il a cessé de mesurer."
    )


def test_every_declared_column_designates_something_that_exists() -> None:
    fautives: list[str] = []
    for fichier, constante, clefs, chemin_modele in _paires():
        module, nom = chemin_modele.rsplit(".", 1)
        app_label = module.split(".")[1]
        try:
            modele = apps.get_model(app_label, nom)
        except LookupError:  # pragma: no cover - modele hors registre
            continue
        for clef in clefs:
            racine = clef.split("__")[0]
            try:
                modele._meta.get_field(racine)
            except Exception:  # noqa: BLE001 - FieldDoesNotExist et variantes
                if not hasattr(modele, racine):
                    fautives.append(f"{fichier} :: {constante} → {nom}.{clef}")

    assert not fautives, (
        "Ces colonnes désignent un champ ou une propriété qui n'existe pas — elles "
        "rendent une cellule vide sur chaque ligne, sans erreur :\n  "
        + "\n  ".join(sorted(fautives))
    )
