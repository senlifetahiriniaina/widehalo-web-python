"""Garde d'interface — aucun commentaire `{# ... #}` ne doit s'etendre sur
plusieurs lignes.

**Django ne supporte PAS le commentaire `{# #}` multi-ligne** : la regex
interne qui le reconnait utilise un `.` qui ne matche pas les sauts de
ligne. Un tel commentaire n'est donc pas retire du gabarit — il est rendu
TEL QUEL dans le HTML envoye au navigateur.

Ce n'est pas cosmetique. Le texte d'un commentaire contient souvent des
noms de balises entre chevrons (« chaque resultat est un `<button>` ») :
le navigateur les parse alors comme de VRAIS elements. C'est arrive dans ce
depot deux fois :

1. `templates/reports/_base.html`, ou le commentaire fuyait jusque dans un
   PDF WeasyPrint reel — le commentaire de ce fichier documente d'ailleurs
   le piege depuis ;
2. `templates/partners/_instant_picker_results.html`, ou un `<button>` cite
   dans un commentaire est devenu un bouton reellement focalisable, capturant
   le focus clavier avant le vrai resultat de recherche — defaut trouve par
   le test de parcours clavier SAL-1, qui echouait sur un
   `document.activeElement` inattendu.

Vingt-quatre commentaires du depot etaient dans ce cas au moment ou cette
garde a ete ecrite. `{% comment %}` est le seul tag Django qui supporte un
commentaire multi-ligne.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def _multiline_inline_comments(text: str) -> list[int]:
    """Numeros de ligne des `{# ... #}` qui traversent un saut de ligne."""
    lines: list[int] = []
    index = 0
    while True:
        start = text.find("{#", index)
        if start == -1:
            return lines
        end = text.find("#}", start)
        if end == -1:
            return lines
        if "\n" in text[start:end]:
            lines.append(text[:start].count("\n") + 1)
        index = end + 2


def test_no_template_uses_a_multiline_inline_comment() -> None:
    problems: list[str] = []
    for template in sorted(TEMPLATES_DIR.rglob("*.html")):
        relative = template.relative_to(TEMPLATES_DIR.parent)
        for line in _multiline_inline_comments(template.read_text(encoding="utf-8")):
            problems.append(f"{relative}:{line}")

    assert not problems, (
        "Commentaire(s) `{# ... #}` sur plusieurs lignes — Django ne les "
        "supprime PAS, leur texte est rendu tel quel dans le HTML (et toute "
        "balise qui y est citee devient un vrai element) :\n"
        + "\n".join(f"  - {problem}" for problem in problems)
        + "\n\nUtiliser `{% comment %}` ... `{% endcomment %}`."
    )


def test_the_detector_actually_detects() -> None:
    """Sans auto-test, cette garde pourrait ne rien detecter et rester verte
    pour la mauvaise raison."""
    faulty = "<div>\n{# une explication\n   sur deux lignes #}\n</div>"
    assert _multiline_inline_comments(faulty) == [2]

    single_line = "<div>{# une explication tenant sur une ligne #}</div>"
    assert _multiline_inline_comments(single_line) == []

    block_form = "<div>\n{% comment %}\nsur deux lignes\n{% endcomment %}\n</div>"
    assert _multiline_inline_comments(block_form) == []
