/*
 * Moteur de recalcul CLIENT du module `simulation` (cahier §13.6).
 *
 * CONTRAT DE PARITÉ SIM-1/SIM-4 — LE PLUS IMPORTANT DE CE FICHIER : ceci
 * est une réimplémentation JavaScript DÉLIBÉRÉMENT ligne-à-ligne de
 * `apps/simulation/services/engine.py::compute_indicators` (mêmes noms,
 * même ordre d'opérations, mêmes points d'arrondi). Toute modification de
 * la formule doit être répercutée DES DEUX CÔTÉS, sous peine de faire
 * échouer *tout* enregistrement de scénario (le serveur recalcule et
 * rejette systématiquement toute divergence, SIM-4).
 *
 * `roundMga`/`round2` implémentent explicitement un arrondi « moitié
 * s'éloigne de zéro » (Decimal.ROUND_HALF_UP côté Python) plutôt que le
 * `Math.round` natif de JS, qui arrondit les négatifs vers +l'infini
 * (Math.round(-2.5) === -2, alors que Python arrondirait -3) — un écart
 * réel bien que rare en pratique (il faudrait qu'un calcul tombe pile sur
 * une demi-unité), corrigé ici plutôt que laissé comme un bug latent.
 */
(function (global) {
  "use strict";

  var TREASURY_WEEKS = 13;
  var TVA_OVERRIDE_NONE = -1;

  function roundHalfAwayFromZero(x) {
    return x < 0 ? -Math.round(-x) : Math.round(x);
  }

  function roundMga(x) {
    return roundHalfAwayFromZero(x);
  }

  function round2(x) {
    return roundHalfAwayFromZero(x * 100) / 100;
  }

  function ecart(value, ref) {
    var delta = value - ref;
    var pct = ref !== 0 ? round2((delta / ref) * 100) : null;
    return { value_mga: delta, pct: pct };
  }

  function clampLevers(rawLevers, catalog) {
    var result = {};
    catalog.forEach(function (lever) {
      result[lever.code] = parseFloat(lever.default);
    });
    Object.keys(rawLevers || {}).forEach(function (code) {
      var lever = null;
      for (var i = 0; i < catalog.length; i++) {
        if (catalog[i].code === code) {
          lever = catalog[i];
          break;
        }
      }
      if (!lever) return;
      var value = parseFloat(rawLevers[code]);
      if (isNaN(value)) return;
      var min = parseFloat(lever.min);
      var max = parseFloat(lever.max);
      result[code] = Math.max(min, Math.min(max, value));
    });
    return result;
  }

  function parseBaseline(raw) {
    var baseline = {};
    Object.keys(raw).forEach(function (key) {
      if (key === "open_items" || key === "as_of_date" || key === "degraded") return;
      baseline[key] = parseFloat(raw[key]);
    });
    baseline.as_of_date = raw.as_of_date;
    baseline.open_items = (raw.open_items || []).map(function (item) {
      return { kind: item.kind, due_date: item.due_date, amount_mga: parseFloat(item.amount_mga) };
    });
    return baseline;
  }

  function daysBetween(isoA, isoB) {
    var a = Date.parse(isoA + "T00:00:00Z");
    var b = Date.parse(isoB + "T00:00:00Z");
    return Math.round((b - a) / 86400000);
  }

  function addDays(iso, days) {
    var d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function computeTreasury(baseline, levers, indicators) {
    var asOf = baseline.as_of_date;
    var startingCash = baseline.starting_cash_mga;
    var inflow = new Array(TREASURY_WEEKS).fill(0);
    var outflow = new Array(TREASURY_WEEKS).fill(0);
    var delaiClient = Math.trunc(levers.delai_client_jours);
    var delaiFournisseur = Math.trunc(levers.delai_fournisseur_jours);

    baseline.open_items.forEach(function (item) {
      var shiftDays = item.kind === "receivable" ? delaiClient : delaiFournisseur;
      var shiftedDue = addDays(item.due_date, shiftDays);
      var weekIndex = Math.floor(daysBetween(asOf, shiftedDue) / 7);
      weekIndex = Math.max(0, Math.min(TREASURY_WEEKS - 1, weekIndex));
      if (item.kind === "receivable") {
        inflow[weekIndex] += item.amount_mga;
      } else {
        outflow[weekIndex] += item.amount_mga;
      }
    });

    var investissementWeek = Math.max(
      0,
      Math.min(TREASURY_WEEKS - 1, Math.trunc(levers.investissement_semaine))
    );
    outflow[investissementWeek] += levers.investissement_mga;

    var resultatDelta = indicators.resultat_net - baseline.resultat_net_ref;
    var opDeltaWeekly = resultatDelta / TREASURY_WEEKS;

    var buckets = [];
    var cumulativeInflow = 0;
    var cumulativeOutflow = 0;
    var cumulativeOpDelta = 0;
    var dipWeek = null;
    for (var index = 0; index < TREASURY_WEEKS; index++) {
      cumulativeInflow += inflow[index];
      cumulativeOutflow += outflow[index];
      cumulativeOpDelta += opDeltaWeekly;
      var balance = roundMga(startingCash + cumulativeInflow - cumulativeOutflow + cumulativeOpDelta);
      buckets.push({
        week: index + 1,
        period_start: addDays(asOf, index * 7),
        inflow_mga: roundMga(inflow[index]),
        outflow_mga: roundMga(outflow[index]),
        balance_mga: balance,
      });
      if (balance < 0 && dipWeek === null) dipWeek = index + 1;
    }

    return {
      starting_cash_mga: roundMga(startingCash),
      buckets: buckets,
      dip_week: dipWeek,
      couverture_jours: dipWeek === null ? null : dipWeek * 7,
    };
  }

  function computeIndicators(baselineRaw, rawLevers, catalog) {
    var baseline = parseBaseline(baselineRaw);
    var levers = clampLevers(rawLevers, catalog);

    var caRef = baseline.ca_ref;
    var achatsRef = baseline.achats_consommes_ref;

    var volumeFactor = 1 + levers.volume_pct / 100;
    var prixFactor = 1 + levers.prix_vente_pct / 100;
    var remiseFactor = 1 - levers.remise_moyenne_pts / 100;
    var ca = roundMga(caRef * volumeFactor * prixFactor * remiseFactor);

    var achatDeltaFactor =
      1 + (levers.cout_matiere_pct + levers.taux_change_pct + levers.transport_douane_pct) / 100;
    var achatsConsommes = roundMga(achatsRef * volumeFactor * achatDeltaFactor);

    var productionExercice = ca + baseline.production_stockee_ref + baseline.production_immobilisee_ref;
    var consommationExercice = achatsConsommes;
    var valeurAjoutee = productionExercice - consommationExercice;

    var chargesPersonnel = roundMga(baseline.charges_personnel_ref * (1 + levers.masse_salariale_pct / 100));
    var structureFactor = 1 + levers.charges_fixes_pct / 100;
    var impotsTaxes = roundMga(baseline.impots_taxes_ref * structureFactor);
    var dotations = roundMga(baseline.dotations_ref * structureFactor);

    var excedentBrut =
      valeurAjoutee + baseline.subvention_exploitation_ref - chargesPersonnel - impotsTaxes;
    var resultatOperationnel = excedentBrut + baseline.autres_produits_operationnels_ref - dotations;

    var chargesFinancieres = roundMga(
      baseline.charges_financieres_ref * (1 + levers.frais_financiers_pct / 100)
    );
    var resultatFinancier = baseline.produits_financiers_ref - chargesFinancieres;

    var resultatAvantImpot = resultatOperationnel + resultatFinancier;
    var resultatNet = resultatAvantImpot - baseline.impot_resultats_ref;

    var marge = ca - achatsConsommes;
    var tauxMarge = ca !== 0 ? marge / ca : 0;

    var chargesFixesTotales = chargesPersonnel + impotsTaxes + dotations + chargesFinancieres;
    var seuilRentabilite = tauxMarge > 0 ? roundMga(chargesFixesTotales / tauxMarge) : null;

    var tvaOverride = levers.tva_taux_override_pct;
    var tvaTaux = tvaOverride === TVA_OVERRIDE_NONE ? baseline.tva_taux_ref : tvaOverride;
    var tvaCollectee = roundMga((ca * tvaTaux) / 100);
    var tvaDeductible = roundMga((achatsConsommes * tvaTaux) / 100);
    var tvaNetteProjetee = tvaCollectee - tvaDeductible;

    var margeRef = caRef - achatsRef;

    var indicators = {
      ca: ca,
      achats_consommes: achatsConsommes,
      valeur_ajoutee: valeurAjoutee,
      charges_personnel: chargesPersonnel,
      impots_taxes: impotsTaxes,
      dotations: dotations,
      excedent_brut: excedentBrut,
      resultat_operationnel: resultatOperationnel,
      charges_financieres: chargesFinancieres,
      resultat_financier: resultatFinancier,
      resultat_avant_impot: resultatAvantImpot,
      resultat_net: resultatNet,
      marge: marge,
      taux_marge_pct: round2(tauxMarge * 100),
      seuil_rentabilite: seuilRentabilite,
      tva_taux: tvaTaux,
      tva_collectee: tvaCollectee,
      tva_deductible: tvaDeductible,
      tva_nette_projetee: tvaNetteProjetee,
      ecarts: {
        ca: ecart(ca, caRef),
        marge: ecart(marge, margeRef),
        excedent_brut: ecart(excedentBrut, baseline.ebe_ref),
        resultat_net: ecart(resultatNet, baseline.resultat_net_ref),
      },
    };
    indicators.treasury = computeTreasury(baseline, levers, indicators);
    return indicators;
  }

  global.SimEngine = {
    computeIndicators: computeIndicators,
    clampLevers: clampLevers,
    parseBaseline: parseBaseline,
  };
})(window);
