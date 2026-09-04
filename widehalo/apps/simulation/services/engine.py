"""Moteur de recalcul déterministe du module `simulation` (cahier §13.6).

**Contrat de parité SIM-1/SIM-4, le plus important de ce fichier** : ce
module est la SEULE source de vérité pour la formule de recalcul —
`static/js/simulation_engine.js` en est une réimplémentation JavaScript
DÉLIBÉRÉMENT ligne-à-ligne (mêmes noms, même ordre d'opérations, mêmes
points d'arrondi), pour que (a) l'atelier de scénarios recalcule tous les
indicateurs en moins de 100 ms côté client sans aller-retour serveur
(SIM-1, « aucun bouton calculer »), et (b) le recalcul serveur à
l'enregistrement (`services.scenarios.create_scenario`/`update_scenario`)
redonne bit-à-bit les mêmes valeurs que ce que le client a affiché
(SIM-4). Toute modification de la formule ci-dessous DOIT être répercutée
dans le fichier JS, sous peine de faire échouer *tout* enregistrement de
scénario (le garde-fou de tolérance rejette alors systématiquement).

Chaque montant MGA est arrondi à l'unité (`_round_mga`, ROUND_HALF_UP) au
même point que son miroir JS (`Math.round`) — l'ariary n'a pas de
décimale usuelle (cahier §7.4, "absence de décimale sauf besoin
explicite"), ce qui rend une parité exacte trivialement atteignable (les
deux runtimes utilisent une arithmétique flottante/décimale largement
plus précise que l'échelle de n'importe quel montant réel d'une PME)."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from apps.simulation.levers import LEVER_CATALOG, TVA_OVERRIDE_NONE, clamp_levers

TREASURY_WEEKS = 13
_ONE = Decimal("1")
_CENT = Decimal("0.01")


def _round_mga(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _ecart(value: Decimal, ref: Decimal) -> dict[str, Any]:
    delta = value - ref
    pct = _round2(delta / ref * 100) if ref != 0 else None
    return {"value_mga": delta, "pct": pct}


def compute_indicators(baseline_data: dict[str, Any], raw_levers: dict[str, Any]) -> dict[str, Any]:
    """Recalcule l'intégralité des indicateurs (compte de résultat
    simplifié, point mort, TVA nette, écarts vs référence, projection de
    trésorerie à 13 semaines) à partir d'un `SimBaseline.data` (déjà
    désérialisé en `Decimal`/`date`, cf. `services.baseline._deserialize_
    baseline_data`) et d'un jeu de leviers bruts (bornés ici via `clamp_
    levers`, jamais transmis tels quels au calcul)."""
    levers = clamp_levers(raw_levers)

    ca_ref = baseline_data["ca_ref"]
    achats_ref = baseline_data["achats_consommes_ref"]

    volume_factor = _ONE + levers["volume_pct"] / 100
    prix_factor = _ONE + levers["prix_vente_pct"] / 100
    remise_factor = _ONE - levers["remise_moyenne_pts"] / 100
    ca = _round_mga(ca_ref * volume_factor * prix_factor * remise_factor)

    achat_delta_factor = (
        _ONE
        + (levers["cout_matiere_pct"] + levers["taux_change_pct"] + levers["transport_douane_pct"])
        / 100
    )
    achats_consommes = _round_mga(achats_ref * volume_factor * achat_delta_factor)

    production_exercice = (
        ca + baseline_data["production_stockee_ref"] + baseline_data["production_immobilisee_ref"]
    )
    consommation_exercice = achats_consommes
    valeur_ajoutee = production_exercice - consommation_exercice

    charges_personnel = _round_mga(
        baseline_data["charges_personnel_ref"] * (_ONE + levers["masse_salariale_pct"] / 100)
    )
    structure_factor = _ONE + levers["charges_fixes_pct"] / 100
    impots_taxes = _round_mga(baseline_data["impots_taxes_ref"] * structure_factor)
    dotations = _round_mga(baseline_data["dotations_ref"] * structure_factor)

    excedent_brut = (
        valeur_ajoutee
        + baseline_data["subvention_exploitation_ref"]
        - charges_personnel
        - impots_taxes
    )
    resultat_operationnel = (
        excedent_brut + baseline_data["autres_produits_operationnels_ref"] - dotations
    )

    charges_financieres = _round_mga(
        baseline_data["charges_financieres_ref"] * (_ONE + levers["frais_financiers_pct"] / 100)
    )
    resultat_financier = baseline_data["produits_financiers_ref"] - charges_financieres

    resultat_avant_impot = resultat_operationnel + resultat_financier
    resultat_net = resultat_avant_impot - baseline_data["impot_resultats_ref"]

    marge = ca - achats_consommes
    taux_marge = (marge / ca) if ca != 0 else Decimal(0)

    charges_fixes_totales = charges_personnel + impots_taxes + dotations + charges_financieres
    seuil_rentabilite = _round_mga(charges_fixes_totales / taux_marge) if taux_marge > 0 else None

    tva_override = levers.get("tva_taux_override_pct", TVA_OVERRIDE_NONE)
    tva_taux = baseline_data["tva_taux_ref"] if tva_override == TVA_OVERRIDE_NONE else tva_override
    tva_collectee = _round_mga(ca * tva_taux / 100)
    tva_deductible = _round_mga(achats_consommes * tva_taux / 100)
    tva_nette_projetee = tva_collectee - tva_deductible

    marge_ref = ca_ref - achats_ref

    indicators: dict[str, Any] = {
        "ca": ca,
        "achats_consommes": achats_consommes,
        "valeur_ajoutee": valeur_ajoutee,
        "charges_personnel": charges_personnel,
        "impots_taxes": impots_taxes,
        "dotations": dotations,
        "excedent_brut": excedent_brut,
        "resultat_operationnel": resultat_operationnel,
        "charges_financieres": charges_financieres,
        "resultat_financier": resultat_financier,
        "resultat_avant_impot": resultat_avant_impot,
        "resultat_net": resultat_net,
        "marge": marge,
        "taux_marge_pct": _round2(taux_marge * 100),
        "seuil_rentabilite": seuil_rentabilite,
        "tva_taux": tva_taux,
        "tva_collectee": tva_collectee,
        "tva_deductible": tva_deductible,
        "tva_nette_projetee": tva_nette_projetee,
        "ecarts": {
            "ca": _ecart(ca, ca_ref),
            "marge": _ecart(marge, marge_ref),
            "excedent_brut": _ecart(excedent_brut, baseline_data["ebe_ref"]),
            "resultat_net": _ecart(resultat_net, baseline_data["resultat_net_ref"]),
        },
    }
    indicators["treasury"] = compute_treasury_projection(baseline_data, levers, indicators)
    return indicators


def compute_treasury_projection(
    baseline_data: dict[str, Any], levers: dict[str, Decimal], indicators: dict[str, Any]
) -> dict[str, Any]:
    """SIM-7 : projection de trésorerie à 13 semaines glissantes, ré-
    découpée localement à partir des lignes ouvertes brutes du socle
    (`baseline_data["open_items"]`) — chaque ligne est décalée selon le
    levier de délai de règlement de SON type (client/fournisseur) puis
    replacée dans le panier hebdomadaire résultant, plutôt que de consommer
    un découpage déjà figé (même principe que `apps.accounting.services.
    reports.treasury_forecast`, dont ce calcul est un dérivé « rejouable »)."""
    as_of: dt.date = baseline_data["as_of_date"]
    starting_cash = baseline_data["starting_cash_mga"]

    inflow = [Decimal(0) for _ in range(TREASURY_WEEKS)]
    outflow = [Decimal(0) for _ in range(TREASURY_WEEKS)]
    delai_client_days = int(levers["delai_client_jours"])
    delai_fournisseur_days = int(levers["delai_fournisseur_jours"])

    for item in baseline_data["open_items"]:
        shift_days = delai_client_days if item["kind"] == "receivable" else delai_fournisseur_days
        shifted_due = item["due_date"] + dt.timedelta(days=shift_days)
        week_index = max(0, min(TREASURY_WEEKS - 1, (shifted_due - as_of).days // 7))
        if item["kind"] == "receivable":
            inflow[week_index] += item["amount_mga"]
        else:
            outflow[week_index] += item["amount_mga"]

    investissement_week = max(0, min(TREASURY_WEEKS - 1, int(levers["investissement_semaine"])))
    outflow[investissement_week] += levers["investissement_mga"]

    # Effet cash approché de l'écart de résultat vs référence, lissé sur
    # les 13 semaines — simplification documentée (le moteur ne modélise
    # pas un compte de résultat encaissé jour par jour), cohérente avec le
    # garde-fou cahier « un scénario n'est pas un budget » : cette ligne
    # n'est qu'un ORDRE DE GRANDEUR de l'effet trésorerie d'un résultat
    # différent, jamais une prévision comptable engagée.
    resultat_delta = indicators["resultat_net"] - baseline_data["resultat_net_ref"]
    op_delta_weekly = resultat_delta / TREASURY_WEEKS

    buckets: list[dict[str, Any]] = []
    cumulative_inflow = Decimal(0)
    cumulative_outflow = Decimal(0)
    cumulative_op_delta = Decimal(0)
    dip_week: int | None = None
    for index in range(TREASURY_WEEKS):
        cumulative_inflow += inflow[index]
        cumulative_outflow += outflow[index]
        cumulative_op_delta += op_delta_weekly
        balance = _round_mga(
            starting_cash + cumulative_inflow - cumulative_outflow + cumulative_op_delta
        )
        week_start = as_of + dt.timedelta(days=index * 7)
        buckets.append(
            {
                "week": index + 1,
                "period_start": week_start.isoformat(),
                "inflow_mga": _round_mga(inflow[index]),
                "outflow_mga": _round_mga(outflow[index]),
                "balance_mga": balance,
            }
        )
        if balance < 0 and dip_week is None:
            dip_week = index + 1

    return {
        "starting_cash_mga": _round_mga(starting_cash),
        "buckets": buckets,
        "dip_week": dip_week,
        "couverture_jours": None if dip_week is None else dip_week * 7,
    }


# Familles de levier proportionnelles éligibles au classement de
# sensibilité (SIM point mort/sensibilité) — les leviers en jours/MGA/
# semaine (délais de règlement, montant/semaine d'investissement) ne sont
# pas comparables sur la même échelle de "poids sur le résultat" qu'un
# nudge en points de pourcentage, donc exclus du classement.
_SENSITIVITY_ELIGIBLE_UNITS = {"%", "pts"}


def rank_levers_by_sensitivity(
    baseline_data: dict[str, Any], raw_levers: dict[str, Any], *, nudge: Decimal = Decimal(1)
) -> list[dict[str, Any]]:
    """Classe les leviers proportionnels par poids réel sur le résultat net
    (cahier §13.6, écran « Point mort et sensibilité » : « classement des
    leviers par poids réel sur le résultat — pour savoir sur quoi agir en
    priorité »). Méthode : nudge +1 point/pourcent de CHAQUE levier
    indépendamment (les autres restant à la valeur du scénario courant),
    mesure l'écart sur `resultat_net`, trie par écart absolu décroissant."""
    levers = clamp_levers(raw_levers)
    base_resultat = compute_indicators(baseline_data, levers)["resultat_net"]

    rankings: list[dict[str, Any]] = []
    for lever in LEVER_CATALOG:
        if lever.unit not in _SENSITIVITY_ELIGIBLE_UNITS:
            continue
        nudged = dict(levers)
        nudged[lever.code] = levers[lever.code] + nudge
        nudged_resultat = compute_indicators(baseline_data, nudged)["resultat_net"]
        delta = nudged_resultat - base_resultat
        rankings.append(
            {
                "code": lever.code,
                "label": lever.label,
                "family": lever.family,
                "delta_resultat_mga": delta,
            }
        )
    rankings.sort(key=lambda row: abs(row["delta_resultat_mga"]), reverse=True)
    return rankings
