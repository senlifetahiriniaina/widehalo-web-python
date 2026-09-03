"""Moteur de recalcul déterministe (`apps.simulation.services.engine`) —
SIM-1 (indicateurs), SIM-5 (aucune écriture, vérifié séparément par
`tests/architecture`), SIM-7 (projection de trésorerie). Fonctions pures,
aucun accès base nécessaire."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from apps.simulation.levers import LEVER_CATALOG, default_levers
from apps.simulation.services.engine import compute_indicators, rank_levers_by_sensitivity

_BASELINE_DATA: dict[str, object] = {
    "ca_ref": Decimal("100000000"),
    "achats_consommes_ref": Decimal("40000000"),
    "production_stockee_ref": Decimal(0),
    "production_immobilisee_ref": Decimal(0),
    "subvention_exploitation_ref": Decimal(0),
    "charges_personnel_ref": Decimal("20000000"),
    "impots_taxes_ref": Decimal("1000000"),
    "autres_produits_operationnels_ref": Decimal(0),
    "dotations_ref": Decimal("2000000"),
    "produits_financiers_ref": Decimal(0),
    "charges_financieres_ref": Decimal("500000"),
    "impot_resultats_ref": Decimal("3000000"),
    "ebe_ref": Decimal("39000000"),
    # Cohérent avec la cascade réellement produite par `compute_indicators`
    # à leviers nuls sur les AUTRES champs ci-dessus (valeur_ajoutee 60M -
    # charges_personnel 20M - impots_taxes 1M = EBE 39M ; EBE - dotations
    # 2M = résultat opérationnel 37M ; + résultat financier (0 - 500K) =
    # 36.5M avant impôt ; - impôt sur les résultats 3M = 33.5M) — un socle
    # réel (`services.baseline.build_baseline`) est TOUJOURS cohérent par
    # construction (ebe_ref/resultat_net_ref proviennent de la MÊME
    # cascade `income_statement` que achats_consommes_ref/charges_
    # personnel_ref/etc., cf. `_STATEMENT_LABELS`), donc « leviers nuls
    # reproduit la référence » est un invariant réel, pas un artefact de
    # ce jeu de données synthétique.
    "resultat_net_ref": Decimal("33500000"),
    "tva_taux_ref": Decimal("20"),
    "starting_cash_mga": Decimal("15000000"),
    "as_of_date": dt.date(2026, 9, 1),
    "open_items": [
        {"kind": "receivable", "due_date": dt.date(2026, 9, 15), "amount_mga": Decimal("5000000")},
        {"kind": "payable", "due_date": dt.date(2026, 9, 20), "amount_mga": Decimal("3000000")},
    ],
}


def test_zero_levers_reproduces_reference_values() -> None:
    indicators = compute_indicators(_BASELINE_DATA, default_levers())
    assert indicators["ca"] == Decimal("100000000")
    assert indicators["achats_consommes"] == Decimal("40000000")
    assert indicators["marge"] == Decimal("60000000")
    assert indicators["resultat_net"] == Decimal("33500000")
    assert indicators["excedent_brut"] == Decimal("39000000")
    assert indicators["tva_taux"] == Decimal("20")
    for row in indicators["ecarts"].values():
        assert row["value_mga"] == 0
        assert row["pct"] == 0


def test_prix_vente_lever_scales_ca_but_not_achats() -> None:
    levers = {**default_levers(), "prix_vente_pct": Decimal(10)}
    indicators = compute_indicators(_BASELINE_DATA, levers)
    assert indicators["ca"] == Decimal("110000000")
    assert indicators["achats_consommes"] == Decimal("40000000")
    assert indicators["marge"] == Decimal("70000000")
    assert indicators["ecarts"]["ca"]["value_mga"] == Decimal("10000000")
    assert indicators["ecarts"]["ca"]["pct"] == Decimal("10.00")


def test_volume_lever_scales_ca_and_achats_together() -> None:
    levers = {**default_levers(), "volume_pct": Decimal(10)}
    indicators = compute_indicators(_BASELINE_DATA, levers)
    assert indicators["ca"] == Decimal("110000000")
    assert indicators["achats_consommes"] == Decimal("44000000")


def test_remise_lever_reduces_ca() -> None:
    levers = {**default_levers(), "remise_moyenne_pts": Decimal(10)}
    indicators = compute_indicators(_BASELINE_DATA, levers)
    assert indicators["ca"] == Decimal("90000000")


def test_seuil_rentabilite_is_none_when_margin_is_not_positive() -> None:
    baseline_data = {**_BASELINE_DATA, "achats_consommes_ref": Decimal("150000000")}
    indicators = compute_indicators(baseline_data, default_levers())
    assert indicators["seuil_rentabilite"] is None


def test_tva_override_replaces_reference_rate() -> None:
    levers = {**default_levers(), "tva_taux_override_pct": Decimal(18)}
    indicators = compute_indicators(_BASELINE_DATA, levers)
    assert indicators["tva_taux"] == Decimal(18)
    assert indicators["tva_collectee"] == Decimal("18000000")
    assert indicators["tva_deductible"] == Decimal("7200000")


def test_treasury_projection_buckets_open_items_by_week() -> None:
    indicators = compute_indicators(_BASELINE_DATA, default_levers())
    buckets = indicators["treasury"]["buckets"]
    assert len(buckets) == 13
    # Recevable au 15/09 (14 jours apres le 01/09) et payable au 20/09
    # (19 jours apres) tombent tous deux dans le panier hebdomadaire
    # d'indice 2 (jours 14-20), donc "week" == 3 (1-indexe).
    assert buckets[0]["balance_mga"] == Decimal("15000000")
    assert buckets[1]["balance_mga"] == Decimal("15000000")
    assert buckets[2]["balance_mga"] == Decimal("17000000")
    assert indicators["treasury"]["dip_week"] is None
    assert indicators["treasury"]["couverture_jours"] is None


def test_delai_client_lever_shifts_receivable_to_a_later_bucket() -> None:
    levers = {**default_levers(), "delai_client_jours": Decimal(30)}
    indicators = compute_indicators(_BASELINE_DATA, levers)
    buckets = indicators["treasury"]["buckets"]
    # Le recevable (5M) part de l'indice 2 (14 jours) vers l'indice 6
    # (14+30=44 jours -> 44//7=6) ; le payable (3M, inchange) reste a
    # l'indice 2.
    assert buckets[2]["balance_mga"] == Decimal("12000000")
    assert buckets[6]["balance_mga"] == Decimal("17000000")


def test_investissement_lever_produces_a_one_time_outflow() -> None:
    levers = {
        **default_levers(),
        "investissement_mga": Decimal("2000000"),
        "investissement_semaine": Decimal(4),
    }
    indicators = compute_indicators(_BASELINE_DATA, levers)
    buckets = indicators["treasury"]["buckets"]
    assert buckets[4]["outflow_mga"] == Decimal("2000000")


def test_sensitivity_ranking_only_covers_proportional_levers() -> None:
    rankings = rank_levers_by_sensitivity(_BASELINE_DATA, default_levers())
    eligible_codes = {
        lever.code for lever in LEVER_CATALOG if lever.unit in ("%", "pts")
    }
    assert {row["code"] for row in rankings} == eligible_codes
    # Trie decroissant par ecart absolu sur le resultat net.
    deltas = [abs(row["delta_resultat_mga"]) for row in rankings]
    assert deltas == sorted(deltas, reverse=True)


def test_sensitivity_ranking_prix_vente_has_a_real_effect_on_resultat() -> None:
    rankings = rank_levers_by_sensitivity(_BASELINE_DATA, default_levers())
    by_code = {row["code"]: row for row in rankings}
    assert by_code["prix_vente_pct"]["delta_resultat_mga"] != 0
