"""Catalogue de leviers (`apps.simulation.levers`) — bornes, sentinelle
TVA, filtrage des clés inconnues."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.simulation.levers import TVA_OVERRIDE_NONE, clamp_levers, default_levers


def test_default_levers_are_all_zero_except_tva_override_sentinel() -> None:
    defaults = default_levers()
    assert defaults["tva_taux_override_pct"] == TVA_OVERRIDE_NONE
    for code, value in defaults.items():
        if code == "tva_taux_override_pct":
            continue
        assert value == Decimal(0)


def test_clamp_levers_drops_unknown_keys() -> None:
    result = clamp_levers({"prix_vente_pct": 5, "levier_invente": 999})
    assert "levier_invente" not in result
    assert result["prix_vente_pct"] == Decimal(5)


def test_clamp_levers_clamps_out_of_bound_values() -> None:
    result = clamp_levers({"prix_vente_pct": 999})
    assert result["prix_vente_pct"] == Decimal(100)  # borne haute du catalogue

    result = clamp_levers({"prix_vente_pct": -999})
    assert result["prix_vente_pct"] == Decimal(-50)  # borne basse du catalogue


def test_clamp_levers_raises_on_non_numeric_value() -> None:
    with pytest.raises(ValueError, match="invalide"):
        clamp_levers({"prix_vente_pct": "pas un nombre"})


def test_tva_override_sentinel_survives_a_clamp_roundtrip() -> None:
    """Régression : la sentinelle -1 (« pas de dérogation ») DOIT survivre
    à `clamp_levers` même lorsqu'elle est explicitement renvoyée par
    l'appelant (le client soumet toujours le jeu complet des leviers
    courants, sentinelle par défaut comprise) — si la borne basse du
    levier `tva_taux_override_pct` était fixée à 0 plutôt qu'à -1, ce test
    échouerait (la sentinelle serait écrasée à 0 à chaque réenregistrement
    d'un scénario qui n'utilise pas la dérogation)."""
    result = clamp_levers({"tva_taux_override_pct": -1})
    assert result["tva_taux_override_pct"] == TVA_OVERRIDE_NONE


def test_missing_levers_default_to_zero_or_sentinel() -> None:
    result = clamp_levers({})
    assert result == default_levers()
