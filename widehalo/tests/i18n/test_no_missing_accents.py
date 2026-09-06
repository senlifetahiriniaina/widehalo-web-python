"""Garde-fou i18n (ACC5) : reapplique le mecanisme de detection d'accents
manquants (ACC1, factorise dans `_accent_utils.py`) sur l'etat COURANT du
depot et echoue si un nouveau mot corrigible-avec-certitude apparait dans
le texte utilisateur (templates `{% trans %}`/`{% blocktrans %}`, appels
gettext/`*_CHOICES` Python, champs `label`/`name`/`description`/`notes`/
`kpi_label` des 8 fixtures de reference) — empeche la regression sur un
futur chantier delegue a un agent en arriere-plan (cf. plan, chantier
"correction systematique des accents manquants dans le texte utilisateur").

Ce garde-fou ne verifie PAS que le depot est parfaitement accentue partout
(hors de portee : docstrings/commentaires developpeur, ~11 000 occurrences
explicitement exclues par decision actee avec l'utilisateur) — seulement
qu'aucun mot NOUVEAU, mecaniquement corrigible sans ambiguite par aspell,
ne s'est glisse dans le perimetre texte-utilisateur depuis la cloture du
chantier ACC1-ACC4. Un reliquat de mots "ambigus" (plusieurs restaurations
d'accent valides selon le contexte, cf. `MANUAL_OVERRIDES` et sa docstring
pour la liste disclosee des cas non resolus) est un etat FINAL attendu et
n'est jamais une regression a lui seul — seul `auto_fix` (jamais
`ambiguous`) doit rester vide."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.i18n._accent_utils import (
    FIXTURE_FILES_AND_FIELDS,
    REPO_ROOT,
    compute_auto_fix_dictionary,
    extract_fixture_strings,
    extract_python_strings,
    extract_template_strings,
    words_from_strings,
)


def _aspell_available() -> bool:
    if shutil.which("aspell") is None:
        return False
    try:
        subprocess.run(
            ["aspell", "-l", "fr", "-a"],  # noqa: S607
            input="test",
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _aspell_available(),
    reason=(
        "aspell/aspell-fr non disponible dans cet environnement — garde-fou "
        "ignore plutot qu'en echec (CI l'installe explicitement, cf. "
        ".github/workflows/ci.yml)."
    ),
)


def _current_state_words() -> set[str]:
    words: set[str] = set()

    templates_dir = REPO_ROOT / "templates"
    for path in sorted(templates_dir.rglob("*.html")):
        words |= words_from_strings(extract_template_strings(path))

    apps_dir = REPO_ROOT / "apps"
    for path in sorted(apps_dir.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if "migrations" in rel.parts or "tests" in rel.parts:
            continue
        words |= words_from_strings(extract_python_strings(path))

    for rel_path, fields in FIXTURE_FILES_AND_FIELDS.items():
        words |= words_from_strings(extract_fixture_strings(REPO_ROOT / rel_path, fields))

    return words


def test_no_auto_correctable_missing_accents_remain() -> None:
    """Le chantier ACC1-ACC4 a ramene `auto_fix` a zero sur ces trois
    sources — ce test echoue avec la liste exacte des mots fautifs si un
    futur changement en reintroduit (regression), et NE compte jamais un
    mot deja documente comme ambigu (`ambiguous`, jamais auto-corrige par
    construction, cf. docstring de `compute_auto_fix_dictionary`)."""
    words = _current_state_words()
    auto_fix, _ambiguous = compute_auto_fix_dictionary(words)
    assert not auto_fix, (
        "Mots sans accent auto-corrigibles avec certitude detectes dans le texte "
        "utilisateur (templates {% trans %}/{% blocktrans %}, appels gettext/"
        "*_CHOICES Python, champs label/name/description/notes/kpi_label des "
        "fixtures de reference) — corriger a la source (jamais dans ce test) :\n"
        + "\n".join(f"  {word} -> {fix}" for word, fix in sorted(auto_fix.items()))
    )


def test_the_proper_noun_exclusion_actually_excludes() -> None:
    """Auto-test de `PROPER_NOUNS`. Sans lui, l'exclusion pourrait ne rien
    exclure (une faute de frappe dans l'entrée suffit) et « Meta » serait
    de nouveau proposé à la correction — en CI seulement, puisque cette
    garde est ignorée là où aspell manque.

    On vérifie les DEUX sens : le mot exclu ne remonte pas, et un mot
    comparable qui n'est PAS dans la liste remonte bien. Sans la seconde
    moitié, une exclusion qui avalerait tout serait indiscernable d'une
    exclusion correcte."""
    from tests.i18n._accent_utils import PROPER_NOUNS

    assert "Meta" in PROPER_NOUNS

    auto_fix, ambiguous = compute_auto_fix_dictionary({"Meta", "referentiel"})
    assert "Meta" not in auto_fix
    assert "Meta" not in ambiguous
    assert auto_fix.get("referentiel") == "référentiel", (
        "L'exclusion des noms propres avale des mots qu'elle ne devrait pas : "
        "la garde ne protège plus rien."
    )


def test_the_proper_noun_list_has_no_obsolete_entry() -> None:
    """Une exception qui survit au texte qui la justifiait devient une
    permission tacite : elle autoriserait plus tard un vrai mot français
    homographe sans que personne ne rejoue la décision. Même discipline que
    la liste d'exception de `test_whatsapp_single_send_path`."""
    from tests.i18n._accent_utils import PROPER_NOUNS

    words = _current_state_words()
    unused = sorted(noun for noun in PROPER_NOUNS if noun not in words)
    assert not unused, (
        f"Nom(s) propre(s) exempté(s) mais absent(s) du texte utilisateur : {unused}. "
        "Retirer l'entrée plutôt que de la garder « au cas où »."
    )


def test_a_case_only_suggestion_is_never_an_auto_fix() -> None:
    """Une suggestion qui ne diffère de l'original que par la CASSE ne
    restaure aucun accent — et l'appliquer dégraderait le texte.

    Trouvé en livrant S1 : aspell proposait « d'API » → « d'api », classé
    comme une correction *certaine* parce que `strip_accents("d'api")`
    égale bien `"d'api"`. « Clé d'API » serait devenu « Clé d'api ». Le
    même piège attend tout sigle français précédé d'une élision : d'ONU,
    d'OTAN, d'UE.

    Le remède est dans le DÉTECTEUR, pas dans une liste d'exceptions : y
    inscrire « d'API » aurait fermé le cas et laissé les autres ouverts."""
    auto_fix, ambiguous = compute_auto_fix_dictionary({"d'API", "referentiel"})

    assert "d'API" not in auto_fix
    assert "d'API" not in ambiguous
    # Et le détecteur continue de voir les vraies fautes : sans cette
    # moitié, un filtre qui rejetterait tout satisferait aussi la première.
    assert auto_fix.get("referentiel") == "référentiel"
