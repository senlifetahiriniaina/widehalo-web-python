"""Bloc F, F3 (FOR-14, §5.6.2 sous-séquencement `forecast` — cf. plan) :
charge d'atelier PROJETÉE VS. RÉALISÉ. Réutilise TEL QUEL le protocole de
rétrotest déjà construit pour la prévision de ventes (`services/engine.py`
— `select_model`/`MODEL_FUNCTIONS`, série-agnostique, aucune duplication
de la logique statistique), appliqué ici à un historique d'HEURES
RÉELLEMENT RÉALISÉES par atelier plutôt qu'à un historique de valeur de
ventes.

**Conception assumée et disclosée** (recherche préalable, aucun texte
source FOR-14 plus précis que sa paraphrase dans le plan/l'audit) :

- Grain "atelier" (`MrpWorkshop`), jamais "poste de charge"
  (`MrpWorkcenter`) : c'est la seule granularité où l'heure RÉELLEMENT
  RÉALISÉE est enregistrée de façon fiable aujourd'hui — `MrpCra` (le
  compte-rendu d'activité validé) porte un `workshop`, jamais un
  `workcenter` distinct.
- STATELESS, comme `apps.forecast.services.material_needs` (F1) et
  `apps.strategy.services.capacity_review.build_capacity_outlook`
  (CAP1-2, le précédent le plus proche structurellement) : AUCUNE
  persistance, AUCUNE migration. `ForSeriesForecast` (le modèle qui
  porte déjà rétrotest+erreur pour la prévision de ventes) n'est
  délibérément PAS réutilisé ici — son `dimension_type` est un choix
  fermé de dimensions de VENTE (famille/article/client/canal) en
  Ariary, consommé tel quel par la simulation financière
  (`ForPublication`/`services.public.get_latest_published_forecast`) ;
  y injecter des heures d'atelier sous un nouveau `dimension_type`
  corromprait cette sémantique pour ce consommateur. Ajouter un 5ᵉ
  modèle dédié dépasserait le budget d'architecture auto-imposé de ce
  module ("4 modèles seulement", cf. docstring `models.py`) sans
  qu'aucun besoin de persistance/historique propre ne le justifie —
  l'historique réel reste dans `MrpCra`, jamais dupliqué ici, même
  principe que le reste de ce module vis-à-vis d'`apps.analytics`.
- "Projeté VS. réalisé" (titre du sprint) est répondu par la marche
  avant du rétrotest lui-même, jamais par une prévision future comparée
  à une valeur qui n'existe pas encore : pour les `test_periods`
  derniers mois déjà échus, `history` ci-dessous rejoue localement le
  modèle SÉLECTIONNÉ (déjà choisi par `select_model` sur cette même
  fenêtre) période par période, en n'utilisant que les données
  antérieures à chaque étape (même discipline "jamais l'historique
  complet" que `engine.backtest`) — cette petite reconstitution locale
  (quelques lignes, fonctions candidates pures/sans DB) est un choix
  délibéré plutôt que d'élargir le contrat public de `engine.backtest`
  (qui ne renvoie que des paires `(réel, prédit)` sans date attachée)
  pour tous ses appelants existants (prévision de ventes) — évite de
  faire ricocher un changement de contrat partagé jusque dans un module
  déjà livré et testé, pour un besoin d'affichage propre à ce sprint.
- `forward` (les `horizon_months` mois à VENIR) n'a par construction
  aucun réalisé : `realized_hours` n'existe pas sur ces lignes (jamais
  un `None`/`0` trompeur substitué) — utile pour comparer la charge
  projetée à la capacité déclarée (`workload_pct`), assemblant enfin les
  deux briques que l'audit identifie comme "disponibles mais non
  assemblées" (capacité `MrpWorkshop.capacity_hours_day` +
  `apps.forecast.services.calendar.business_days_in_month`, FOR-5).
- Aucun `ForExceptionalPoint` : ce mécanisme est réservé aux 4
  dimensions de vente existantes (rupture d'appro, promo isolée...),
  hors périmètre de ce sprint (ni le plan ni l'audit ne le demandent) —
  l'historique réalisé est utilisé brut.
- Zéro nouvel écran (budget à 240/240, zéro marge) : greffé comme
  nouvel onglet dans l'écran existant `forecast/index.html`, même
  discipline que F2 (`config_reordering_rules.html`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.forecast.services.calendar import business_days_in_month
from apps.forecast.services.engine import MODEL_FUNCTIONS, select_model
from apps.mrp.services.public import get_workshop_realized_hours_series, list_workshops

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

# Même valeur par défaut que `engine.select_model`/`services.compute.
# compute_and_store_forecast` — mêmes fenêtres de rétrotest/horizon que
# la prévision de ventes, pour rester fidèle au protocole réutilisé.
DEFAULT_HISTORY_MONTHS = 36
DEFAULT_HORIZON_MONTHS = 6
DEFAULT_TEST_PERIODS = 6

# Même repli minimal que `engine.backtest` (`min_train_size`) — jamais
# un entraînement sur moins de 2 points.
_MIN_TRAIN_SIZE = 2


def _next_month(period: dt.date) -> dt.date:
    """Identique à `services/compute.py::_next_month` — petite fonction
    utilitaire dupliquée délibérément (2 lignes) plutôt que partagée via
    un module utilitaire créé pour une seule fonction."""
    return (period.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def _capacity_hours(tenant: Tenant, capacity_hours_day: Decimal, period: dt.date) -> Decimal:
    working_days = business_days_in_month(tenant, period.year, period.month)
    return capacity_hours_day * Decimal(working_days)


def compute_workshop_workload_forecast(
    tenant: Tenant,
    *,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    history_months: int = DEFAULT_HISTORY_MONTHS,
    test_periods: int = DEFAULT_TEST_PERIODS,
) -> list[dict[str, Any]]:
    """FOR-14 : une entrée par atelier actif (non sous-traitant, cf.
    `list_workshops`). Retourne des primitives uniquement :

    ``{"workshop_id", "workshop_code", "workshop_name",
    "selected_model", "insufficient_history_for_seasonality",
    "error_mae_pct", "error_weighted_pct", "error_bias_pct",
    "history": [{"period", "projected_hours", "realized_hours",
    "realized_error_pct"}, ...], "forward": [{"period",
    "projected_hours", "capacity_hours", "workload_pct"}, ...]}``.

    `get_workshop_realized_hours_series` renvoie toujours exactement
    `history_months` entrées (mois sans CRA validé inclus à
    `Decimal(0)`, jamais un trou) : un atelier sans aucun CRA validé
    obtient donc une série plate à zéro, PAS une série vide — le modèle
    sélectionné projette alors honnêtement une charge nulle, jamais un
    `None` masquant l'absence de données. `selected_model=None`/
    `history=[]`/`forward=[]` ne se produit que si `history_months<=0`
    est demandé explicitement (paramètre dégénéré) — jamais une
    exception, même discipline "jamais de faux positif" que le reste de
    ce module et de `apps.mrp.services.public`."""
    results: list[dict[str, Any]] = []
    for workshop in list_workshops(tenant):
        series = get_workshop_realized_hours_series(tenant, workshop["id"], periods=history_months)
        periods = [row["period"] for row in series]
        values = [row["value"] for row in series]

        selection = select_model(periods, values, test_periods=test_periods)
        if selection is None:
            results.append(
                {
                    "workshop_id": workshop["id"],
                    "workshop_code": workshop["code"],
                    "workshop_name": workshop["name"],
                    "selected_model": None,
                    "insufficient_history_for_seasonality": False,
                    "error_mae_pct": None,
                    "error_weighted_pct": None,
                    "error_bias_pct": None,
                    "history": [],
                    "forward": [],
                }
            )
            continue

        model_fn = MODEL_FUNCTIONS[selection.selected_model]
        float_values = [float(v) for v in values]
        months = [p.month for p in periods]

        # "Projeté vs. réalisé" (périodes déjà échues) : marche avant du
        # modèle SÉLECTIONNÉ sur la même fenêtre que `select_model`,
        # jamais l'historique complet à chaque étape — cf. docstring de
        # module pour la justification de cette petite reconstitution
        # locale plutôt qu'un élargissement du contrat de `engine.backtest`.
        history_rows: list[dict[str, Any]] = []
        start = max(len(periods) - test_periods, _MIN_TRAIN_SIZE)
        for i in range(start, len(periods)):
            predicted = model_fn(float_values[:i], months[:i])
            projected_hours = Decimal(str(round(predicted, 4)))
            realized_hours = values[i]
            realized_error_pct = (
                abs(realized_hours - projected_hours) / abs(realized_hours) * 100
                if realized_hours
                else None
            )
            history_rows.append(
                {
                    "period": periods[i],
                    "projected_hours": projected_hours,
                    "realized_hours": realized_hours,
                    "realized_error_pct": realized_error_pct,
                }
            )

        # Projection à venir (jamais de réalisé — l'avenir n'en a aucun).
        forward_values = list(float_values)
        forward_months = list(months)
        last_period = periods[-1] if periods else dt.date.today().replace(day=1)
        forward_rows: list[dict[str, Any]] = []
        for _ in range(horizon_months):
            last_period = _next_month(last_period)
            predicted = model_fn(forward_values, forward_months)
            forward_values.append(predicted)
            forward_months.append(last_period.month)
            projected_hours = Decimal(str(round(predicted, 4)))
            capacity_hours = _capacity_hours(tenant, workshop["capacity_hours_day"], last_period)
            workload_pct = projected_hours / capacity_hours * 100 if capacity_hours else None
            forward_rows.append(
                {
                    "period": last_period,
                    "projected_hours": projected_hours,
                    "capacity_hours": capacity_hours,
                    "workload_pct": workload_pct,
                }
            )

        results.append(
            {
                "workshop_id": workshop["id"],
                "workshop_code": workshop["code"],
                "workshop_name": workshop["name"],
                "selected_model": selection.selected_model,
                "insufficient_history_for_seasonality": (
                    selection.insufficient_history_for_seasonality
                ),
                "error_mae_pct": selection.error_mae_pct,
                "error_weighted_pct": selection.error_weighted_pct,
                "error_bias_pct": selection.error_bias_pct,
                "history": history_rows,
                "forward": forward_rows,
            }
        )
    return results
