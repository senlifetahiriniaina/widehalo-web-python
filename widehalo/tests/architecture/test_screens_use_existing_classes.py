"""Garde T9 : aucun ecran ne porte une classe qui n'existe nulle part.

**Le defaut que cette garde ferme, et il etait massif.** Une classe CSS
absente de la feuille ne casse RIEN de visible a la construction : le
navigateur l'ignore, l'element herite de ce qui traine, et l'ecran s'affiche
— mal, mais il s'affiche. Aucun test, aucun linter, aucune revue ne le
signale. C'est le pendant, cote presentation, du motif « rien de decoratif »
que ce chantier corrige cote code : du markup ecrit, coherent, relu, et sans
effet.

Mesure a l'ouverture du lot T9 : **79 gabarits sur 291** portaient au moins
une classe inexistante. Trois causes, et aucune n'etait une faute de frappe :

1. Des utilitaires jamais ecrits (`hint`, `text-muted`, `bandeau`,
   `filters`, `form-success`, `wh-panel`, `b-warning`) — la classe disait la
   bonne chose, le systeme de design ne l'avait simplement pas.
2. Sept repertoires employaient du Tailwind/DaisyUI **sans etre scannes** par
   le build : leurs classes ne figuraient dans aucune feuille produite.
3. Des noms **DaisyUI 4** (`tabs-boxed`, `input-bordered`, `select-bordered`)
   restes en place quand la dependance est passee en version 5.

Apres correction des trois : 34 gabarits, 47 classes, listees ci-dessous.

**Pourquoi une dette declaree plutot qu'un echec immediat.** Definir les 47
restantes demande des choix de conception — `sim-grid`, `report-header`,
`wizard-steps` ne se devinent pas depuis leur nom — et les inventer a la
hate produirait une mise en forme arbitraire, ce qui est pire qu'une classe
morte. La liste ne peut que diminuer : deux tests d'obsolescence refusent
qu'une entree y reste apres avoir ete definie, ou qu'elle y traine sans
designer aucun gabarit.
"""

from __future__ import annotations

import pathlib
import re

RACINE = pathlib.Path(__file__).resolve().parents[2]
CSS = RACINE / "static" / "css"
TEMPLATES = RACINE / "templates"

#: La dette mesuree au lot T9. Y ajouter une entree demande de justifier
#: pourquoi un ecran neuf porterait une classe qui n'existe pas.
DETTE_CONNUE = {
    "automation-palette",  # 1 gabarit(s)
    "button",  # 1 gabarit(s)
    "button-disabled",  # 1 gabarit(s)
    "c-chart",  # 1 gabarit(s)
    "c-dashboard-grid",  # 2 gabarit(s)
    "c-metric-value",  # 2 gabarit(s)
    "duplicata",  # 1 gabarit(s)
    "error",  # 1 gabarit(s)
    "gantt-container",  # 2 gabarit(s)
    "grand",  # 1 gabarit(s)
    "inline-form",  # 2 gabarit(s)
    "kanban-column",  # 2 gabarit(s)
    "kanban-handle",  # 2 gabarit(s)
    "meta",  # 1 gabarit(s)
    "placeholder",  # 1 gabarit(s)
    "pos-layout",  # 1 gabarit(s)
    "qlt-item-row",  # 1 gabarit(s)
    "report-footer",  # 1 gabarit(s)
    "report-header",  # 1 gabarit(s)
    "report-header-company",  # 1 gabarit(s)
    "report-header-company-text",  # 1 gabarit(s)
    "report-header-doc",  # 1 gabarit(s)
    "report-legal-mention",  # 1 gabarit(s)
    "report-logo",  # 1 gabarit(s)
    "report-table",  # 5 gabarit(s)
    "row-selected",  # 1 gabarit(s)
    "row-warning",  # 1 gabarit(s)
    "sim-compare-grid",  # 1 gabarit(s)
    "sim-grid",  # 1 gabarit(s)
    "sim-indicators",  # 1 gabarit(s)
    "sim-lever-row",  # 1 gabarit(s)
    "sim-levers",  # 1 gabarit(s)
    "sim-save-form",  # 1 gabarit(s)
    "stack-inline",  # 1 gabarit(s)
    "tag",  # 1 gabarit(s)
    "totals",  # 1 gabarit(s)
    "wh-assist-result",  # 1 gabarit(s)
    "wh-data-query-result",  # 1 gabarit(s)
    "wh-data-query-sources",  # 1 gabarit(s)
    "wh-empty-state",  # 1 gabarit(s)
    "wh-launcher",  # 1 gabarit(s)
    "wh-launcher-user-results",  # 1 gabarit(s)
    "wh-nl-search-result",  # 1 gabarit(s)
    "wh-partner-picker-display",  # 1 gabarit(s)
    "wizard-step-label",  # 1 gabarit(s)
    "wizard-step-number",  # 1 gabarit(s)
    "wizard-steps",  # 1 gabarit(s)
}


def _classes_definies() -> set[str]:
    r"""Toutes les classes que les feuilles de style declarent.

    **Deux regles, et les ignorer sous-compte** — le pire des deux sens pour
    une garde comme celle-ci, puisqu'elle signalerait comme manquantes des
    classes parfaitement definies. Un selecteur de classe s'arrete au premier
    point NON echappe : `.badge.b-success` en declare DEUX. Et les
    utilitaires Tailwind portent des caracteres echappes dans leur nom :
    `.sm\:flex`, `.min-h-\[56px\]`, `.text-base-content\/60`.

    L'erreur a ete commise quatre fois avant d'ecrire cette fonction, et
    chaque version fausse donnait un chiffre different — 118, puis 106, puis
    90, puis 63 classes « manquantes ». La bonne reponse est 47."""
    css = "\n".join(p.read_text() for p in CSS.glob("*.css"))
    brutes = re.findall(r"\.((?:[a-zA-Z0-9_-]|\\.)+)", css)
    return {re.sub(r"\\(.)", r"\1", b) for b in brutes}


def _classes_employees() -> dict[str, set[str]]:
    """Les classes ecrites dans les gabarits, et ou.

    Les attributs qui contiennent une balise Django ou une apostrophe sont
    ignores : `class="{% if x %}a{% else %}b{% endif %}"` et les liaisons
    Alpine `:class="..."` ne sont pas des listes de classes, et en tirer des
    jetons produirait un bruit (`{%`, `===`, `item.level`) qui masquerait les
    vrais manques."""
    trouvees: dict[str, set[str]] = {}
    for chemin in sorted(TEMPLATES.rglob("*.html")):
        for attribut in re.findall(r'(?<!:)class="([^"]*)"', chemin.read_text()):
            if "{" in attribut or "'" in attribut:
                continue
            for classe in attribut.split():
                trouvees.setdefault(classe, set()).add(str(chemin.relative_to(RACINE)))
    return trouvees


def test_no_screen_carries_a_class_that_exists_nowhere() -> None:
    """**LE critere.** Un ecran qui porte une classe inexistante s'affiche
    sans la mise en forme que son auteur croyait lui donner."""
    definies = _classes_definies()
    employees = _classes_employees()
    manquantes = {
        classe: fichiers
        for classe, fichiers in employees.items()
        if classe not in definies and classe not in DETTE_CONNUE
    }
    assert not manquantes, (
        "Classe(s) employee(s) dans un gabarit et definie(s) nulle part :\n"
        + "\n".join(
            f"  {classe} -> {sorted(fichiers)}" for classe, fichiers in sorted(manquantes.items())
        )
        + "\n\nSoit la classe s'ecrit dans `static/css/app.css`, soit le gabarit "
        "emploie une classe existante. Une classe absente ne casse rien de "
        "visible a la construction : c'est precisement pour cela qu'il faut "
        "une garde."
    )


def test_the_declared_debt_never_survives_its_fix() -> None:
    """La dette est un plafond, pas un budget : une entree definie depuis
    doit SORTIR de la liste.

    Sans ce test, elle deviendrait un depotoir ou personne ne saurait plus ce
    qui reste a faire — exactement ce qu'une derogation muette produit
    partout ailleurs."""
    definies = _classes_definies()
    perimees = sorted(classe for classe in DETTE_CONNUE if classe in definies)
    assert not perimees, (
        f"Ces classes sont desormais definies et doivent sortir de `DETTE_CONNUE` : {perimees}"
    )


def test_the_declared_debt_still_designates_used_classes() -> None:
    """Une entree qui ne designe plus aucun gabarit laisse croire a une dette
    qui n'existe plus."""
    employees = _classes_employees()
    orphelines = sorted(classe for classe in DETTE_CONNUE if classe not in employees)
    assert not orphelines, (
        f"Ces entrees de `DETTE_CONNUE` ne sont employees par aucun gabarit "
        f"et doivent en sortir : {orphelines}"
    )
