"""Contrat generique de resolution d'entite pour la qualification/
identification universelle des donnees importees (chantier RG-QUALIF).

Ce module ne contient AUCUNE donnee d'entite metier (ni `Partner`, ni
`ProductVariant`, ni `AccAccount`...) — respect strict de la regle de
couplage n°1 : chaque app expose ses propres `resolve_<kind>(...)` dans
son propre `apps.<app>.services.public`, qui retournent un
`ResolutionResult` construit avec les types definis ICI. `core` ne
connait donc jamais un modele metier concret, seulement le vocabulaire
partage de resolution.

**Discipline "jamais de devinette"** (meme principe que
`apps.accounting.services.bank_reconciliation.suggest_matches`) : une
resolution `FUZZY` ne doit JAMAIS etre retournee sur 0 ou 2+ candidats
approximatifs — uniquement sur une correspondance candidate UNIQUE. 0 ou
2+ candidats = `UNRESOLVED`, jamais une auto-decision."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ResolutionConfidence(StrEnum):
    """Niveau de confiance d'une resolution de reference externe (nom
    libre -> entite reelle du referentiel)."""

    EXACT = "exact"
    """Correspondance exacte (apres normalisation, cf. `normalize_name`)."""

    FUZZY = "fuzzy"
    """Correspondance approximative, mais UNIQUE parmi les candidats —
    jamais retourne s'il existe 0 ou 2+ candidats plausibles."""

    UNRESOLVED = "unresolved"
    """Aucune entite ne peut etre retenue avec certitude (0 candidat ou
    ambiguite entre plusieurs) — jamais d'auto-decision."""


@dataclass(frozen=True)
class ResolutionResult:
    """Resultat partage d'une tentative de resolution `resolve_<kind>(...)`
    portee par chaque app metier. `entity_id` est `None` si et seulement si
    `confidence is ResolutionConfidence.UNRESOLVED` — invariant verifie par
    les appelants, pas par ce dataclass (reste un simple conteneur de
    donnees, aucune logique metier ici)."""

    confidence: ResolutionConfidence
    entity_id: UUID | None
    is_placeholder: bool = False


def normalize_name(value: str) -> str:
    """Normalisation partagee pour la correspondance EXACTE d'un nom libre
    importe (accents retires, casse repliee, espaces multiples
    compresses) — utilisee par chaque `resolve_<kind>` module pour
    comparer un nom source au referentiel existant. Volontairement simple
    (v1 "exact-normalise uniquement", cf. `apps.partners.services.public.
    find_partner_by_name`) : aucun algorithme de similarite avance
    (Levenshtein, phonetique...) n'est implemente ici — simplification
    assumee et documentee, amelioration possible ulterieure."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.strip().lower().split())
