"""Previsions de demande (§5.5.3/5.5.9, S6 du sous-sequencement `sales`,
cf. plan) : RG-SAL-7 (tableau produit x periode demande/capacite/ecart/
cause dominante), RG-SAL-8 (methodes statistiques simples et
explicables uniquement, aucun ML) et SAL-SAIS1 (coefficient saisonnier
mensuel sur trois exercices, methode explicable non predictive).

**Discipline RG-SAL-8** : chaque nombre produit ici doit pouvoir etre
explique a un humain par une formule ecrite a la main, jamais une boite
noire. Chaque fonction documente sa formule exacte. Aucune bibliotheque
de ML/statistiques n'est utilisee au-dela de ce qui est deja une
dependance du projet.

**Frontiere de stub heritee de RG-SAL-3/S3** (cf. `services.procurement`) :
`apps.stocks` n'existe pas encore dans ce lot — la colonne "cause
dominante" du tableau RG-SAL-7 n'inclut donc JAMAIS "stock", seulement
"capacite"/"delai_fournisseur"/"aucun". C'est une limitation documentee,
pas un bug (cf. plan, decision RG-SAL-7)."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.catalog.services.public import get_supplier_lead_time_days
from apps.core.models.tenant import Tenant
from apps.crm.services.public import pipeline_weighted_demand
from apps.mrp.services.public import get_total_workshop_capacity
from apps.sales.models import SalesForecast, SalesOrderLine, SalesRecurrence

# Lissage exponentiel simple (RG-SAL-8) : alpha = 0.4 pondere le mois le
# plus recent a 40% du niveau lisse precedent, un compromis courant et
# documentable (plus reactif qu'un alpha faible type 0.2, plus stable
# qu'un alpha eleve type 0.7) — pas de justification statistique plus
# fine recherchee ici, conformement a RG-SAL-8 ("l'explicabilite prime
# sur la precision a cette echelle").
_SMOOTHING_ALPHA = Decimal("0.4")

# SAL-SAIS1 : nombre minimal de mois d'historique (tous mois confondus,
# pas necessairement consecutifs) avant qu'un coefficient saisonnier soit
# calcule plutot que suppose neutre (1.0). 12 mois est le minimum pour
# avoir vu chaque mois calendaire au moins une fois : en dessous, un ecart
# mensuel observe est plus probablement du bruit qu'une vraie saisonnalite.
_MIN_MONTHS_FOR_SEASONALITY = 12

# SAL-SAIS1 : "calcule sur trois exercices" — fenetre glissante de 36 mois.
_SEASONALITY_WINDOW_MONTHS = 36

# Garde-fou de securite pour l'estimation de la composante recurrence
# (`_recurring_component_for_period`) : borne le nombre d'occurrences
# simulees par gabarit pour ne jamais boucler indefiniment sur une
# recurrence mal configuree (ex. `interval` incoherent).
_MAX_RECURRENCE_OCCURRENCES = 60


def _month_bucket(date: dt.date) -> str:
    return date.strftime("%Y-%m")


def _period_bounds(period: str) -> tuple[dt.date, dt.date]:
    """Convertit un bucket mensuel "YYYY-MM" en `(premier_jour,
    dernier_jour)` du mois."""
    year, month = (int(part) for part in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def historical_average_demand(tenant: Tenant, variant_id: Any, *, months: int = 3) -> Decimal:
    """RG-SAL-7/8 : combine une moyenne mobile ponderee (WMA) et un
    lissage exponentiel simple (ES) sur l'historique de **quantites
    livrees** (`SalesOrderLine.qty_delivered`) des `months` derniers mois
    calendaires, comme litteralement nomme par le CDC ("moyenne mobile
    ponderee ET lissage exponentiel simple").

    Formule exacte, en 4 etapes :

    1. Les lignes livrees (`qty_delivered > 0`) du variant sur la fenetre
       sont regroupees par mois calendaire (`order.date`), donnant une
       serie `[m_1, ..., m_N]` (du plus ancien au plus recent), `N <=
       months`.
    2. **WMA** : poids lineaires croissants `1, 2, ..., N` (le mois le
       plus recent pese le plus) :
       `WMA = sum(m_i * i) / sum(i)` pour `i` de 1 a N.
    3. **ES** : `S_1 = m_1` puis `S_i = alpha * m_i + (1 - alpha) *
       S_(i-1)` pour `i` de 2 a N (`alpha = 0.4`, cf. `_SMOOTHING_ALPHA`) ;
       l'estimation ES retenue est `S_N` (dernier niveau lisse).
    4. **Combinaison** : moyenne simple `(WMA + S_N) / 2` — un melange
       50/50, documente ici comme le choix le plus simple qui utilise
       reellement les deux techniques nommees par le CDC plutot que d'en
       ignorer une.

    Retourne `Decimal(0)` (jamais une exception) si aucune ligne livree
    n'existe sur la fenetre."""
    since = timezone.now().date().replace(day=1) - relativedelta(months=months - 1)

    lines = SalesOrderLine.objects.filter(
        order__tenant=tenant,
        variant_id=variant_id,
        qty_delivered__gt=0,
        order__date__gte=since,
    ).values_list("order__date", "qty_delivered")

    monthly_totals: dict[str, Decimal] = {}
    for order_date, qty_delivered in lines:
        bucket = _month_bucket(order_date)
        monthly_totals[bucket] = monthly_totals.get(bucket, Decimal(0)) + qty_delivered

    if not monthly_totals:
        return Decimal(0)

    series = [monthly_totals[bucket] for bucket in sorted(monthly_totals)]
    n = len(series)

    weight_sum = Decimal(sum(range(1, n + 1)))
    wma = sum((series[i] * Decimal(i + 1) for i in range(n)), Decimal(0)) / weight_sum

    smoothed = series[0]
    for value in series[1:]:
        smoothed = _SMOOTHING_ALPHA * value + (Decimal(1) - _SMOOTHING_ALPHA) * smoothed

    return ((wma + smoothed) / Decimal(2)).quantize(Decimal("0.0001"))


def seasonal_coefficient(tenant: Tenant, variant_id: Any, month: int) -> Decimal:
    """SAL-SAIS1 : "coefficient saisonnier mensuel calcule sur trois
    exercices [...] methode explicable, non predictive."

    Formule : sur les `_SEASONALITY_WINDOW_MONTHS` (36) derniers mois de
    quantites livrees du variant, `coefficient = moyenne(demande du mois
    calendaire `month`) / moyenne(demande, tous mois confondus)`. Un
    coefficient de 1.5 signifie "ce mois vend en moyenne 50% de plus que
    la moyenne des mois" ; 0.5 signifie moitie moins.

    Retourne `Decimal(1)` (aucun effet saisonnier) si l'historique compte
    moins de `_MIN_MONTHS_FOR_SEASONALITY` (12) mois distincts de donnees,
    ou si la moyenne toutes periodes est nulle — un signal insuffisant ne
    doit jamais produire un coefficient fabrique."""
    since = timezone.now().date() - relativedelta(months=_SEASONALITY_WINDOW_MONTHS)
    lines = SalesOrderLine.objects.filter(
        order__tenant=tenant,
        variant_id=variant_id,
        qty_delivered__gt=0,
        order__date__gte=since,
    ).values_list("order__date", "qty_delivered")

    monthly_totals: dict[str, Decimal] = {}
    for order_date, qty_delivered in lines:
        bucket = _month_bucket(order_date)
        monthly_totals[bucket] = monthly_totals.get(bucket, Decimal(0)) + qty_delivered

    if len(monthly_totals) < _MIN_MONTHS_FOR_SEASONALITY:
        return Decimal(1)

    overall_avg = sum(monthly_totals.values(), Decimal(0)) / Decimal(len(monthly_totals))
    if overall_avg == 0:
        return Decimal(1)

    target_values = [
        qty for bucket, qty in monthly_totals.items() if int(bucket.split("-")[1]) == month
    ]
    if not target_values:
        return Decimal(1)
    month_avg = sum(target_values, Decimal(0)) / Decimal(len(target_values))

    return (month_avg / overall_avg).quantize(Decimal("0.0001"))


def customer_calendar_adjustment(
    tenant: Tenant, partner_id: Any, period_start: dt.date, period_end: dt.date
) -> Decimal:
    """RG-SAL-7 (composante "calendrier client") : somme brute des
    `impact_pct` de chaque `SalesCustomerCalendar` du partenaire dont la
    plage `[date_from, date_to]` chevauche `[period_start, period_end]`.

    Simplification assumee documentee : une simple somme, jamais de
    logique d'interaction/compounding entre deux evenements qui se
    chevaucheraient (ex. une fermeture ET un pic la meme semaine) — le
    resultat serait alors juste la somme algebrique des deux, pas un
    produit ou une regle de priorite. Retourne `Decimal(0)` si aucun
    chevauchement."""
    from apps.sales.models import SalesCustomerCalendar

    overlapping = SalesCustomerCalendar.objects.filter(
        tenant=tenant,
        partner_id=partner_id,
        date_from__lte=period_end,
        date_to__gte=period_start,
    )
    total = Decimal(0)
    for entry in overlapping:
        total += entry.impact_pct
    return total


def _recurring_component_for_period(
    tenant: Tenant, variant_id: Any, period_start: dt.date, period_end: dt.date
) -> Decimal:
    """RG-SAL-7 (composante "commandes recurrentes planifiees") :
    estimation simple, PAS une simulation complete — parcourt chaque
    `SalesRecurrence` active du tenant dont le gabarit contient une ligne
    pour `variant_id`, et compte combien d'occurrences (a partir de
    `next_run`, au pas `interval`) tombent dans `[period_start,
    period_end]`, bornees par `end_date` et par
    `_MAX_RECURRENCE_OCCURRENCES` (garde-fou anti-boucle). Chaque
    occurrence contribue la `qty` de la ligne du gabarit."""
    from apps.sales.services.recurrence import _INTERVAL_STEPS

    total = Decimal(0)
    recurrences = SalesRecurrence.objects.filter(tenant=tenant, is_active=True).select_related(
        "template_order"
    )
    for recurrence in recurrences:
        qty_per_occurrence = sum(
            (
                line.qty
                for line in recurrence.template_order.lines.all()
                if line.variant_id == variant_id
            ),
            Decimal(0),
        )
        if not qty_per_occurrence:
            continue

        step = _INTERVAL_STEPS[recurrence.interval]
        occurrence = recurrence.next_run
        occurrences_in_period = 0
        for _ in range(_MAX_RECURRENCE_OCCURRENCES):
            if occurrence > period_end:
                break
            if recurrence.end_date is not None and occurrence > recurrence.end_date:
                break
            if occurrence >= period_start:
                occurrences_in_period += 1
            occurrence = occurrence + step

        total += qty_per_occurrence * occurrences_in_period
    return total


def build_forecast(
    tenant: Tenant, variant_id: Any, period: str, *, partner_id: Any = None
) -> SalesForecast:
    """RG-SAL-7 : orchestrateur de prevision produit x periode.

    `qty_forecast` combine :
    - `historical_average_demand(...)`, ajustee par le coefficient
      saisonnier du mois de `period` — application retenue : simple
      multiplication (`base * coefficient`), documentee ici comme un
      ratio applique a la moyenne historique, pas un ajustement additif ;
    - la composante pipeline CRM pondere (`crm.services.public.
      pipeline_weighted_demand`, valeur du variant si presente) ;
    - la composante commandes recurrentes planifiees
      (`_recurring_component_for_period`) ;
    - si `partner_id` est fourni, un ajustement calendrier client
      (`customer_calendar_adjustment`), applique comme un multiplicateur
      `(1 + impact_pct / 100)` sur la somme des trois composantes
      ci-dessus (une fermeture -100% ramene la demande a zero, un pic
      +50% l'augmente d'autant) — coherent avec la simplicite "somme
      brute" documentee sur `customer_calendar_adjustment` elle-meme.

    Ecart capacite/delai (RG-SAL-7, "c'est cet ecart qui a une valeur
    operationnelle") : la capacite atelier (`mrp.services.public.
    get_total_workshop_capacity`) est un nombre d'heures/jour BRUT, jamais
    convertie en une quantite-produit precise (aucune donnee de temps de
    gamme fiable a ce niveau, cf. docstring de
    `get_total_workshop_capacity`) — elle est exposee telle quelle dans
    `parameters["capacity_hours_day"]` pour lecture humaine. Le seul
    signal capacite assez sur pour piloter `dominant_cause` reste le cas
    extreme "capacite totale nulle" (aucun atelier non sous-traitant) : au
    dela, fabriquer un seuil precis serait une fausse precision
    (RG-SAL-8). Le delai fournisseur (`catalog.services.public.
    get_supplier_lead_time_days`), lui, est directement comparable en
    jours au nombre de jours restant avant le debut de la periode.

    `dominant_cause` (jamais `"stock"`, cf. docstring module), par ordre
    de priorite :
    1. `"delai_fournisseur"` si un delai fournisseur est connu et depasse
       le nombre de jours restant avant `period_start` (matiere commandee
       trop tard vu le lead time) ;
    2. `"capacite"` si la capacite atelier totale du tenant est nulle et
       qu'une demande non nulle est prevue (aucune capacite de production
       propre) ;
    3. `"aucun"` sinon.

    Persistance `get_or_create`-style : une ligne par
    `(tenant, period, variant_id, partner_id)`, mise a jour en place si
    elle existe deja (une prevision est recalculable, jamais dupliquee)."""
    period_start, period_end = _period_bounds(period)
    today = timezone.now().date()

    historical = historical_average_demand(tenant, variant_id)
    coefficient = seasonal_coefficient(tenant, variant_id, period_start.month)
    seasonal_adjusted = (historical * coefficient).quantize(Decimal("0.0001"))

    pipeline = pipeline_weighted_demand(tenant)
    crm_component = pipeline.get(str(variant_id), Decimal(0))

    recurring_component = _recurring_component_for_period(
        tenant, variant_id, period_start, period_end
    )

    qty_forecast = seasonal_adjusted + crm_component + recurring_component

    calendar_adjustment_pct: Decimal | None = None
    if partner_id is not None:
        calendar_adjustment_pct = customer_calendar_adjustment(
            tenant, partner_id, period_start, period_end
        )
        qty_forecast = qty_forecast * (Decimal(1) + calendar_adjustment_pct / Decimal(100))

    qty_forecast = qty_forecast.quantize(Decimal("0.0001"))
    if qty_forecast < 0:
        qty_forecast = Decimal(0)

    capacity_hours_day = get_total_workshop_capacity(tenant)
    lead_time_days = get_supplier_lead_time_days(variant_id, partner_id=partner_id)
    days_until_period_start = (period_start - today).days

    dominant_cause = "aucun"
    if lead_time_days is not None and lead_time_days > days_until_period_start:
        dominant_cause = "delai_fournisseur"
    elif capacity_hours_day == 0 and qty_forecast > 0:
        dominant_cause = "capacite"

    # Confiance (heuristique simple, RG-SAL-8) : basee uniquement sur la
    # profondeur d'historique reellement utilisee par
    # `historical_average_demand` (fenetre de 3 mois par defaut) — plus il
    # y a de mois avec des livraisons reelles, plus l'estimation
    # historique est fiable.
    months_with_history = SalesOrderLine.objects.filter(
        order__tenant=tenant, variant_id=variant_id, qty_delivered__gt=0
    ).values_list("order__date", flat=True)
    distinct_months = {_month_bucket(d) for d in months_with_history}
    if len(distinct_months) >= 3:
        confidence = SalesForecast.CONFIDENCE_HIGH
    elif len(distinct_months) >= 1:
        confidence = SalesForecast.CONFIDENCE_MEDIUM
    else:
        confidence = SalesForecast.CONFIDENCE_LOW

    parameters: dict[str, Any] = {
        "historical_avg": str(historical),
        "seasonal_coefficient": str(coefficient),
        "seasonal_adjusted_demand": str(seasonal_adjusted),
        "crm_pipeline_component": str(crm_component),
        "recurring_component": str(recurring_component),
        "customer_calendar_adjustment_pct": (
            str(calendar_adjustment_pct) if calendar_adjustment_pct is not None else None
        ),
        # Signal reel mais BRUT (heures/jour, non converti en
        # quantite-produit — cf. docstring `get_total_workshop_capacity`).
        "capacity_hours_day": str(capacity_hours_day),
        "lead_time_days": lead_time_days,
        "days_until_period_start": days_until_period_start,
        "dominant_cause": dominant_cause,
    }

    variant_uuid = UUID(str(variant_id))
    partner_uuid = UUID(str(partner_id)) if partner_id is not None else None

    forecast = SalesForecast.objects.filter(
        tenant=tenant, period=period, variant_id=variant_uuid, partner_id=partner_uuid
    ).first()
    if forecast is None:
        forecast = SalesForecast(
            tenant=tenant, period=period, variant_id=variant_uuid, partner_id=partner_uuid
        )

    forecast.qty_forecast = qty_forecast
    forecast.confidence = confidence
    forecast.method = "weighted_moving_average+exponential_smoothing"
    forecast.parameters = parameters
    forecast.save()
    return forecast


def recompute_forecasts_for_period(tenant: Tenant, period: str) -> list[SalesForecast]:
    """Point d'entree de `POST /api/v1/sales/forecast/recompute` : recalcule
    une prevision produit (toutes clientes confondues, `partner_id=None`)
    pour chaque variante ayant eu une activite de commande dans les 12
    derniers mois du tenant — un perimetre "tous les variants ayant deja
    ete vendus depuis toujours" grossirait sans borne et previrait des
    produits abandonnes depuis des annees ; 12 mois est le meme ordre de
    grandeur que la fenetre de saisonnalite/historique deja utilisee
    ailleurs dans ce module."""
    one_year_ago = timezone.now().date() - dt.timedelta(days=365)
    variant_ids = (
        SalesOrderLine.objects.filter(
            order__tenant=tenant, variant_id__isnull=False, order__date__gte=one_year_ago
        )
        .values_list("variant_id", flat=True)
        .distinct()
    )
    return [build_forecast(tenant, variant_id, period) for variant_id in variant_ids]
