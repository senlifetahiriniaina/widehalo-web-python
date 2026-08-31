"""Utilitaire partage : extraction du texte utilisateur (FR) de ce depot et
detection mecanique des mots orthographies sans accent, via `aspell -l fr`.

**Perimetre "texte utilisateur uniquement"** (decision actee avec
l'utilisateur, cf. plan section "correction systematique des accents
manquants") :
- Templates : contenu de `{% trans "..." %}`/`{% blocktrans %}...
  {% endblocktrans %}`.
- Python : arguments de chaine des appels `_()`/`gettext()`/
  `gettext_lazy()`/`pgettext()`/`pgettext_lazy()`/`ngettext()`/
  `ngettext_lazy()`, plus les libelles (elements de tuple) des listes
  `*_CHOICES = [...]` de niveau module (convention deja etablie dans ce
  depot pour les `choices=` de champ de modele — jamais un `choices=[...]`
  inline, verifie par audit avant d'ecrire ce module). `apps/*/module.py`
  est explicitement exclu : son kwarg `verbose_name=` sur `ModuleSpec` est
  une metadonnee d'architecture jamais rendue a l'ecran (verifie par
  recherche exhaustive avant d'ecrire ce module), pas du texte utilisateur.
- Fixtures : champs `label`/`name`/`description`/`notes`/`kpi_label` des 8
  fichiers de referentiel deja livres (charges en base puis affiches).

**Mecanisme de detection, sur mesure et volontairement conservateur** : un
mot n'est retenu comme correction sure que si `aspell -l fr` le signale
comme mal orthographie ET que retirer les accents de sa PREMIERE
suggestion reproduit EXACTEMENT le mot original — exclut mecaniquement les
mots courts ambigus selon le contexte (deja valides tels quels, jamais
signales), les acronymes/codes metier/termes anglais (aucune correspondance
accent-seul valide), sans aucune supposition linguistique risquee. Voir le
pilote reel documente dans le plan pour la validation de cette methode."""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_TRANS_RE = re.compile(r'{%\s*trans\s+"((?:[^"\\]|\\.)*)"\s*%}')
_BLOCKTRANS_RE = re.compile(r"{%\s*blocktrans[^%]*%}(.*?){%\s*endblocktrans\s*%}", re.S)
_TEMPLATE_VAR_RE = re.compile(r"{{.*?}}")

_GETTEXT_CALL_RE = re.compile(
    r'\b(?:_|gettext|gettext_lazy|pgettext|pgettext_lazy|ngettext|ngettext_lazy)\('
    r'\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
)
_CHOICES_BLOCK_RE = re.compile(r"_CHOICES(?::\s*[\w\[\], \.\"']+)?\s*=\s*\[(.*?)\n\]", re.S)
_QUOTED_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:'[A-Za-zÀ-ÖØ-öø-ÿ]+)?")

FIXTURE_FILES_AND_FIELDS: dict[str, tuple[str, ...]] = {
    "apps/helpdesk/fixtures/ticket_type_catalog.json": ("label",),
    "apps/accounting/fixtures/pcg2005_mg.json": ("name", "name_en"),
    "apps/catalog/fixtures/materials_reference_mg.json": ("name", "usage_notes"),
    "apps/catalog/fixtures/customization_options.json": ("name", "notes"),
    "apps/catalog/fixtures/epi_standards.json": ("name", "description"),
    "apps/catalog/fixtures/sample_products_by_family.json": ("name",),
    "apps/catalog/fixtures/sector_certifications.json": ("name",),
    "apps/strategy/fixtures/textile_mg.json": ("kpi_label",),
}


def strip_accents(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn"
    )


def extract_template_strings(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    strings = _TRANS_RE.findall(content) + _BLOCKTRANS_RE.findall(content)
    return [_TEMPLATE_VAR_RE.sub(" ", s) for s in strings]


def extract_python_strings(path: Path) -> list[str]:
    if path.name == "module.py":
        return []
    content = path.read_text(encoding="utf-8")
    strings: list[str] = []
    for match in _GETTEXT_CALL_RE.finditer(content):
        strings.append(match.group(1) if match.group(1) is not None else match.group(2))
    for block in _CHOICES_BLOCK_RE.findall(content):
        for qmatch in _QUOTED_STRING_RE.finditer(block):
            strings.append(qmatch.group(1) if qmatch.group(1) is not None else qmatch.group(2))
    return strings


def extract_fixture_strings(path: Path, fields: tuple[str, ...]) -> list[str]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    strings: list[str] = []
    for entry in entries:
        for field in fields:
            value = entry.get(field)
            if isinstance(value, str):
                strings.append(value)
    return strings


def words_from_strings(strings: list[str]) -> set[str]:
    words: set[str] = set()
    for s in strings:
        for word in _WORD_RE.findall(s):
            if len(word) >= 3:
                words.add(word)
    return words


def compute_auto_fix_dictionary(words: set[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Retourne `(auto_fix, ambiguous)`.

    `auto_fix` : {mot_original: correction} restreint aux mots pour
    lesquels EXACTEMENT UNE suggestion aspell restaure les accents sans
    changer le mot de base (`strip_accents(suggestion) == mot_original`).

    `ambiguous` : {mot_original: [suggestions candidates]} pour les mots ou
    PLUSIEURS suggestions passent ce meme test — jamais choisi
    automatiquement, meme si une seule "a l'air" plus plausible : trouvaille
    reelle documentee dans le plan (`meme` -> `mémé`/`même` sont TOUS DEUX
    des mots valides une fois les accents retires, aspell classe parfois le
    mauvais en premier — `Precedent` -> `Précèdent` (verbe) vs `Précédent`
    (adjectif/nom) est le meme piege). Ces cas passent par une revue
    manuelle (dictionnaire `MANUAL_OVERRIDES` ci-dessous), jamais une
    supposition automatique sur laquelle des N corrections est la bonne.

    N'invoque jamais aspell sur un ensemble vide (cout nul, aspell
    refuserait une entree vide de toute facon)."""
    if not words:
        return {}, {}
    input_text = "\n".join(sorted(words))
    proc = subprocess.run(
        ["aspell", "-l", "fr", "-a"],
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    auto_fix: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for line in proc.stdout.splitlines():
        if not line or line.startswith("@"):
            continue
        if not (line.startswith("&") or line.startswith("#")):
            continue
        head, _, rest = line.partition(":")
        tokens = head.split()
        original_word = tokens[1]
        suggestions = rest.strip().split(", ") if rest else []
        matches = [s for s in suggestions if strip_accents(s).lower() == original_word.lower()]
        if len(matches) == 1:
            auto_fix[original_word] = matches[0]
        elif len(matches) > 1:
            ambiguous[original_word] = matches
    return auto_fix, ambiguous


# Corrections manuelles pour les cas ou plusieurs restaurations d'accents
# sont mecaniquement valides (cf. docstring de `compute_auto_fix_dictionary`)
# — chaque entree verifiee individuellement dans son contexte reel avant
# d'etre ajoutee ici, jamais une supposition. Applique APRES `auto_fix`,
# jamais a la place (les deux dictionnaires restent disjoints par
# construction : un mot ambigu n'est jamais dans `auto_fix`).
MANUAL_OVERRIDES: dict[str, str] = {
    "meme": "même",
    "Meme": "Même",
    "Precedent": "Précédent",
}


def word_substitution_pattern(word: str) -> re.Pattern[str]:
    """Regex de substitution sure : limites de mot habituelles PLUS un
    lookaround negatif sur le tiret des deux cotes — exclut tout mot
    directement accole a un tiret (protege un code metier compose du type
    `ACC-AGE-C`, cf. trouvaille reelle documentee dans le plan), tout en
    corrigeant le meme mot quand il apparait comme une vraie prose isolee."""
    return re.compile(rf"(?<![A-Za-zÀ-ÖØ-öø-ÿ-]){re.escape(word)}(?![A-Za-zÀ-ÖØ-öø-ÿ-])")
