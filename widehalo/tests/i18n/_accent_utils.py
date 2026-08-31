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
    r"\b(?:_|gettext|gettext_lazy|pgettext|pgettext_lazy|ngettext|ngettext_lazy)\("
    r'\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
)
_CHOICES_BLOCK_RE = re.compile(r"_CHOICES(?::\s*[\w\[\], \.\"']+)?\s*=\s*\[(.*?)\n\]", re.S)
_QUOTED_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')

# Nom de cle d'un placeholder de formatage %-style (`%(role)s`, `%(count)d`,
# ...) - JAMAIS un mot de prose : c'est une cle de dict Python litterale
# utilisee cote appelant (`% {"role": ...}`), jamais accentuee par ce
# chantier (qui ne touche jamais le code Python hors chaines gettext) —
# masque avant extraction des mots candidats, sinon `role`/`debit`/`credit`
# resteraient signales indefiniment par le garde-fou ACC5 sans jamais
# pouvoir etre corriges (la substitution elle-meme les protege deja, cf.
# `apply_python.py` du chantier ACC3).
_FORMAT_PLACEHOLDER_RE = re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)[sdifr]")

# Identifiant Python/JSON litteral cite entre backticks dans un message
# d'erreur (`` `epaisseur_mm` ``, `` `allergenes` ``...) - meme raisonnement
# que `_FORMAT_PLACEHOLDER_RE` ci-dessus (trouvaille reelle du chantier ACC3,
# `apps/catalog/services/sector_specs.py`) : masque avant extraction, sinon
# resterait signale indefiniment par le garde-fou ACC5.
_BACKTICK_IDENTIFIER_RE = re.compile(r"`[a-z_][a-z0-9_]*`")

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:'[A-Za-zÀ-ÖØ-öø-ÿ]+)?")

# Caracteres qui, immediatement accoles a un mot, en font un fragment de
# code metier (`REF3`, `STK-ETAT`, `Gore-Tex`) plutot qu'une vraie prose
# isolee — utilise a la fois par `words_from_strings` (n'extrait meme pas un
# tel mot comme candidat) et par `word_substitution_pattern` (ne le
# substitue jamais). Un ensemble de caracteres, jamais une chaine vide
# testee via `in` (piege reel rencontre : `"" in "-0123456789"` vaut `True`
# en Python, ce qui excluait a tort tout mot en debut/fin de chaine).
_ADJACENCY_GUARD_CHARS = frozenset("-0123456789")

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
    strings = [_FORMAT_PLACEHOLDER_RE.sub(" ", s) for s in strings]
    return [_BACKTICK_IDENTIFIER_RE.sub(" ", s) for s in strings]


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
    """Extrait les mots candidats — exclut par construction tout mot
    directement accole a un tiret OU a un chiffre (meme garde que
    `word_substitution_pattern`, cf. sa docstring pour `REF3`/`STK-ETAT`/
    `Gore-Tex`) : un tel mot n'est PAS une vraie prose isolee, donc jamais
    un candidat legitime — sinon il resterait indefiniment signale par
    `compute_auto_fix_dictionary` (garde-fou ACC5 y compris) sans jamais
    pouvoir etre corrige en toute securite (la substitution elle-meme
    l'exclurait de toute facon)."""
    words: set[str] = set()
    for s in strings:
        for match in _WORD_RE.finditer(s):
            word = match.group(0)
            if len(word) < 3:
                continue
            before = s[match.start() - 1] if match.start() > 0 else None
            after = s[match.end()] if match.end() < len(s) else None
            if before in _ADJACENCY_GUARD_CHARS or after in _ADJACENCY_GUARD_CHARS:
                continue
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
    # `aspell` resolu via PATH : deja le choix assume par ce depot pour cet
    # outil (installe explicitement par la CI et l'environnement de dev,
    # jamais un binaire fourni par l'utilisateur).
    proc = subprocess.run(
        ["aspell", "-l", "fr", "-a"],  # noqa: S607
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
#
# Revue manuelle menee lors du chantier ACC1 sur les 80 mots ambigus reels
# du depot (union templates+python+fixtures) : chaque entree ci-dessous n'a
# ete ajoutee qu'apres verification que TOUTES ses occurrences en zone de
# texte utilisateur partagent le meme role grammatical (ex. "Cloture" == un
# statut/participe "Cloture" dans risk.py/helpdesk/models.py/purchase/
# reports.html : les 5 occurrences designent toutes un etat "ferme" ->
# "Cloture" (nom capitalise, statut ferme) ; utiliser un participe adjectif
# aurait ete grammaticalement correct mais la forme choisie ci-dessous a ete
# verifiee occurrence par occurrence).
#
# **7 mots delibermment LAISSES NON RESOLUS** (limitation assumee et
# documentee, jamais une supposition) car leurs occurrences en zone de texte
# utilisateur melangent reellement plusieurs roles grammaticaux
# incompatibles (nom vs participe/verbe) — verifie au cas par cas (NB : un
# 8e cas, `AGE`, n'existe plus depuis que `words_from_strings` exclut par
# construction tout mot accole a un tiret ou un chiffre — `ACC-AGE-C` ne
# produit meme plus `AGE` comme mot candidat, cf. sa docstring) :
# - `Controle`/`controle` (majuscule) : `payroll/models.py` l'utilise comme
#   participe d'etat (`STATE_CONTROLLED` -> "Controle" = "Controle"/etat
#   controle) alors que les autres occurrences (MRP, boutons "Controle
#   qualite") sont un nom ("le controle qualite") — role incompatible entre
#   occurrences, jamais resolu automatiquement.
# - `reference` (minuscule) : trace tres majoritairement un nom ("la
#   reference", 18 occurrences) mais UNE occurrence
#   (`templates/mrp/config_boms.html`, "Le produit est reference par son
#   UUID") est un participe ("est reference par" = "est referencE par") —
#   conflit reel, laisse tel quel.
# - `Reserve` (majuscule) : melange un participe/adjectif d'etat
#   (`templates/stocks/index.html`, colonne "Reserve" a cote de
#   "Disponible" = quantite reservee), un nom-avertissement repete dans les
#   fixtures ("Reserve non-experte.") et une locution figee ("Sous
#   reserve") — trois roles incompatibles, laisse tel quel.
# - `genere` (minuscule) : verbe present 3e personne dans plusieurs regles
#   metier ("Chaque regle declenchee genere une demande d'achat...") mais
#   participe ailleurs ("insight(s) proactif(s) genere(s)", "ne peut pas
#   etre genere hors contexte tenant") — conflit reel, laisse tel quel
#   (la forme majuscule `Genere`, elle, n'a que des occurrences participe et
#   a ete resolue ci-dessous).
# - `depasse` : verbe present ("l'ecart de consommation depasse le seuil
#   autorise") vs participe/adjectif d'etat ("Plafond de credit depasse")
#   — conflit reel, laisse tel quel.
# - `securise` : aucune des deux suggestions aspell (`securise` verbe,
#   `securise` participe masculin) ne s'accorde correctement avec son
#   unique occurrence reelle ("la recherche... securise par tenant", sujet
#   feminin `la recherche` -> forme correcte `securisee`, hors du jeu de
#   suggestions propose) — laisse tel quel plutot que d'appliquer une forme
#   grammaticalement fausse.
# - `cloture` (minuscule) : 3 occurrences participe ("ticket resolu ou
#   cloture", "avant d'etre cloture", "CRI est deja cloture") mais 1
#   occurrence nom ("a saisir avant la cloture", `logistics/trips.py`) —
#   conflit reel, laisse tel quel (la forme majuscule `Cloture`, elle, n'a
#   que des occurrences participe/statut et a ete resolue ci-dessous).
MANUAL_OVERRIDES: dict[str, str] = {
    "meme": "même",
    "Meme": "Même",
    "Precedent": "Précédent",
    "apres": "après",
    "arrete": "arrêté",
    "budgetise": "budgétisé",
    "chaine": "chaîne",
    "Cloture": "Clôturé",
    "clotures": "clôturés",
    "completes": "complétés",
    "controle": "contrôle",
    "cree": "créé",
    "Declare": "Déclaré",
    "declare": "déclaré",
    "Decompose": "Décompose",
    "Decompte": "Décompte",
    "Decoupe": "Découpe",
    "Dedouane": "Dédouané",
    "dedouane": "dédouané",
    "degrade": "dégradé",
    "Demarre": "Démarré",
    "demarre": "démarré",
    "derive": "dérive",
    "desactive": "désactivé",
    "Detecte": "Détecté",
    "detecte": "détecté",
    "Enquete": "Enquête",
    "epuise": "épuisé",
    "Equipe": "Équipe",
    "equipe": "équipe",
    "Equipes": "Équipes",
    "equipes": "équipes",
    "evalue": "évalué",
    "evenement": "événement",
    "Execute": "Exécuté",
    "Genere": "Généré",
    "Hypotheque": "Hypothèque",
    "Melange": "Mélange",
    "melange": "mélange",
    "necessite": "nécessite",
    "parametre": "paramètre",
    "Parametres": "Paramètres",
    "prefere": "préféré",
    "Prefixe": "Préfixe",
    "presente": "présente",
    "presume": "présumé",
    "procede": "procédé",
    "Redige": "Rédige",
    "redige": "rédige",
    "Reference": "Référence",
    "Regle": "Règle",
    "regle": "règle",
    "Regles": "Règles",
    "Releve": "Relevé",
    "releve": "relevé",
    "Requete": "Requête",
    "requete": "requête",
    "reserve": "réserve",
    "Reserves": "Réserves",
    "Resultat": "Résultat",
    "resultat": "résultat",
    "Resume": "Résumé",
    "Revoque": "Révoqué",
    "serie": "série",
    "specifie": "spécifié",
    "Telephone": "Téléphone",
    "tete": "tête",
    "Unites": "Unités",
    "Vehicule": "Véhicule",
    "vehicule": "véhicule",
    "Vehicules": "Véhicules",
    "vehicules": "véhicules",
}


def word_substitution_pattern(word: str) -> re.Pattern[str]:
    """Regex de substitution sure : limites de mot habituelles PLUS un
    lookaround negatif sur le tiret ET sur le chiffre des deux cotes — exclut
    tout mot directement accole a un tiret (protege un code metier compose du
    type `ACC-AGE-C`, cf. trouvaille reelle documentee dans le plan) OU a un
    chiffre (protege un code/tag du type `REF3`, `STK-ETAT` -> `ETAT`
    apparait aussi directement dans `(STK-ETAT)` donc deja couvert par le
    tiret, mais `REF3` — trouvaille reelle du chantier ACC1, `apps/catalog/
    fixtures/materials_reference_mg.json` : "cf. produits demonstratifs
    REF3" — n'a PAS de tiret, seul le garde-chiffre l'exclut), tout en
    corrigeant le meme mot quand il apparait comme une vraie prose isolee."""
    return re.compile(rf"(?<![A-Za-zÀ-ÖØ-öø-ÿ0-9-]){re.escape(word)}(?![A-Za-zÀ-ÖØ-öø-ÿ0-9-])")
