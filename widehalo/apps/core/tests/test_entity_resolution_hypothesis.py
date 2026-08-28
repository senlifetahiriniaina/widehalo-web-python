"""Test de propriete (couche 13 du CDC, §8) pour le chantier RG-QUALIF
(retest complet des 14 couches — sales/purchase/stocks/logistics +
RG-QUALIF n'existaient pas lors de la premiere passe T9/couche 13).

**Invariant retenu** : `normalize_name` (`apps.core.services.
entity_resolution`, socle partage de resolution EXACTE de chaque
`resolve_<kind>` module, cf. sa docstring) est IDEMPOTENT — normaliser un
nom deja normalise ne doit jamais rien changer, quel que soit le texte
d'entree (accents/casse/espaces arbitraires generes par Hypothesis). C'est
une vraie propriete mathematique (f(f(x)) == f(x)), pas un cas d'exemple :
la fonction sert a comparer un nom source importe (potentiellement saisi
n'importe comment) au referentiel deja normalise, donc son idempotence est
l'invariant dont depend directement la correction de toute la chaine de
resolution EXACTE de RG-QUALIF.

**Pourquoi pas un troisieme invariant `stocks`** : le module `stocks` a
deja ses 2 invariants propres (RG-STK-1 double-entree, RG-STK-2 precision
FIFO, `apps.stocks.tests.test_hypothesis_properties`) construits lors de
son propre chantier ST2/ST7 — les dupliquer ici serait redondant. Aucun
autre candidat de `sales`/`purchase`/`logistics` n'a ete retenu : leurs
regles metier notables (RG-SAL-4 credit, RG-PUR-ROUT1 routage
d'approbation, FSM des expeditions) sont des regles A SEUILS/A ETATS,
mieux couvertes par des exemples deterministes (deja le cas, cf.
`test_orders.py`/`test_structural_constraints.py`) qu'une propriete
generique — forcer une propriete Hypothesis dessus n'aurait rien apporte de
plus que les tests d'exemple existants.

1000 exemples, comme l'exige le critere de sortie de cette couche."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.core.services.entity_resolution import normalize_name


@pytest.mark.slow
@settings(max_examples=1000)
@given(value=st.text(min_size=0, max_size=200))
def test_normalize_name_is_idempotent(value: str) -> None:
    once = normalize_name(value)
    twice = normalize_name(once)
    assert once == twice


@pytest.mark.slow
@settings(max_examples=1000)
@given(value=st.text(min_size=0, max_size=200))
def test_normalize_name_never_raises_and_has_no_leading_trailing_or_double_spaces(
    value: str,
) -> None:
    result = normalize_name(value)
    assert result == result.strip()
    assert "  " not in result
    assert result == result.lower()
