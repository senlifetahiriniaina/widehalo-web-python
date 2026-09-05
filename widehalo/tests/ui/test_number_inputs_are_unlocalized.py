"""Garde d'interface (L14) — un `<input type="number">` prerempli depuis
une variable de gabarit doit passer par `|unlocalize`.

**Le defaut que cette garde ferme, trouve par le test e2e PRD-5.** Sous
locale francaise, Django rend un `Decimal` avec une VIRGULE decimale :
`{{ wo.qty_planned }}` produit `value="5,0000"`. Le navigateur juge cette
valeur invalide pour un champ `type="number"` et rapporte alors une
CHAINE VIDE — ni le formulaire natif ni `FormData` ne transmettent quoi
que ce soit.

Ce que cela donnait en exploitation, verifie :

- `templates/mrp/kanban.html` : chaque « Terminer l'etape » enregistrait
  **0 produite et 0 rejetee** au lieu de la quantite planifiee affichee a
  l'ecran. Le taux de conformite au premier passage (PRD-6) etait donc
  calcule sur des zeros.
- `templates/partners/edit.html` : enregistrer une fiche partenaire sans
  toucher au champ **effacait son encours autorise**.
- `templates/whatsapp/config.html` : enregistrer la configuration
  **effacait le plafond mensuel de cout**.

Aucun test ne pouvait le voir : les tests HTTP postent des valeurs qu'ils
composent eux-memes, jamais celles que le navigateur aurait lues. Il a
fallu un vrai navigateur, sur un test ecrit pour autre chose.

La garde est volontairement TEXTUELLE (lecture des gabarits) et non
comportementale : verifier chaque champ dans un vrai navigateur couterait
un test e2e par ecran, la ou la regle, elle, est simple et verifiable a
l'oeil — et c'est precisement une regle qu'on oublie.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

# `<input ... type="number" ... value="{{ ... }}" ...>`, l'ordre des
# attributs etant libre — d'ou la recherche sur la balise entiere.
_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.DOTALL)
_IS_NUMBER = re.compile(r'type\s*=\s*"number"')
_VALUE_FROM_VARIABLE = re.compile(r'value\s*=\s*"\{\{\s*([^}]+?)\s*\}\}"')


def _offending_inputs() -> list[str]:
    problems: list[str] = []
    for template in sorted(TEMPLATES_DIR.rglob("*.html")):
        text = template.read_text(encoding="utf-8")
        for tag in _INPUT_TAG.findall(text):
            if not _IS_NUMBER.search(tag):
                continue
            match = _VALUE_FROM_VARIABLE.search(tag)
            if match is None:
                continue
            expression = match.group(1)
            if "unlocalize" in expression:
                continue
            line = text[: text.index(tag)].count("\n") + 1
            relative = template.relative_to(TEMPLATES_DIR.parent)
            problems.append(f'{relative}:{line} — value="{{{{ {expression} }}}}"')
    return problems


def test_every_prefilled_number_input_is_unlocalized() -> None:
    problems = _offending_inputs()
    assert not problems, (
        'Champ(s) `type="number"` preremplis sans `|unlocalize` — sous locale '
        "francaise leur valeur est rendue avec une virgule, jugee invalide par le "
        "navigateur, et lue comme une CHAINE VIDE :\n"
        + "\n".join(f"  - {problem}" for problem in problems)
        + "\n\nAjouter `{% load l10n %}` et `|unlocalize` sur la valeur."
    )


def test_the_detector_actually_detects() -> None:
    """Sans auto-test, cette garde pourrait ne rien detecter du tout et
    rester verte pour la mauvaise raison — un theatre de securite. On lui
    soumet la forme exacte du defaut d'origine."""
    faulty = (
        '<input id="q" type="number" name="qty_done" step="0.0001" value="{{ wo.qty_planned }}">'
    )
    assert _IS_NUMBER.search(faulty) is not None
    match = _VALUE_FROM_VARIABLE.search(faulty)
    assert match is not None
    assert "unlocalize" not in match.group(1)

    fixed = faulty.replace("{{ wo.qty_planned }}", "{{ wo.qty_planned|unlocalize }}")
    fixed_match = _VALUE_FROM_VARIABLE.search(fixed)
    assert fixed_match is not None
    assert "unlocalize" in fixed_match.group(1)


def test_a_text_input_is_not_flagged() -> None:
    """La garde ne doit porter que sur `type="number"` : un champ texte
    prerempli avec un nombre localise est legitime (c'est un affichage,
    pas une valeur machine)."""
    text_input = '<input type="text" name="libelle" value="{{ ligne.montant }}">'
    assert _IS_NUMBER.search(text_input) is None
