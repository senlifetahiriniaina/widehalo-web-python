"""Rapports `helpdesk` (HD4, cf. plan section « État d'avancement — HD3
TERMINÉ » -> prochaine etape HD4) : CSAT, performance agent, benchmarking
d'equipe, conformite SLA — QUATRE fonctions PURES/CALCULEES A LA VOLEE
depuis `HlpTicket`/`HlpCsatResponse`/`HlpSlaBreach`, ZERO nouveau modele de
reporting (meme discipline exacte que les ratios `accounting` (A13) ou
`mrp.services.reports.efficiency_report`, cf. plan section modeles ->
« Analytics de performance agent + benchmarking d'equipe »).

**Fenetre temporelle** : `date_from`/`date_to` sont OPTIONNELS ici et
filtrent sur `HlpTicket.created_at` (date de creation du ticket, PAS la
date de resolution/de reponse CSAT) — un ticket cree dans la periode reste
dans le meme "panier" quel que soit le moment ou il a ete effectivement
resolu/note, meme convention que les autres rapports par periode de ce
depot (`sales.services.reports.revenue_report` filtre sur `SalesOrder.
date`). `None` = pas de borne (tout l'historique) ; c'est a l'ecran/l'API
appelant·e de fournir une fenetre par defaut (30 jours glissants, cf.
`views_reports.py`), ces fonctions de service restent agnostiques de tout
defaut d'ecran.

**Choix d'abstraction disclosed** (cf. plan, section 3 : « une petite
fonction privee qui prend un nom de champ de regroupement... ») :
`agent_performance_report`/`team_benchmark_report` partagent un PETIT
helper prive `_ticket_metrics_by_group` (regroupement + agregation brute
identiques : nombre de tickets, nombre resolus/clotures, duree moyenne
premiere-reponse/resolution) — mais restent deux fonctions PUBLIQUES
distinctes, chacune resolvant elle-meme le libelle lisible de son
regroupement (email d'agent vs nom d'equipe, deux resolutions
suffisamment differentes pour ne pas etre fusionnees dans le helper
partage sans le rendre artificiellement generique)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, QuerySet

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.helpdesk.models import HlpCsatResponse, HlpSlaBreach, HlpTeam, HlpTicket

# Etats "termines" au sens rapport (resolu OU cloture) — memes deux etats
# que `csat._SURVEYABLE_STATES`, mais une constante DISTINCTE (couplage
# volontairement faible entre les deux modules de service : le sens
# "peut recevoir une enquete CSAT" et le sens "compte comme traite dans un
# rapport" pourraient diverger a l'avenir sans que l'un n'entraine l'autre).
RESOLVED_OR_CLOSED_STATES = (HlpTicket.STATE_RESOLVED, HlpTicket.STATE_CLOSED)


def _date_filtered_tickets(
    tenant: Tenant, date_from: dt.date | None, date_to: dt.date | None
) -> QuerySet[HlpTicket]:
    queryset = HlpTicket.objects.filter(tenant=tenant, is_active=True)
    if date_from is not None:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


def _duration_to_minutes(duration: dt.timedelta | None) -> float | None:
    if duration is None:
        return None
    return round(duration.total_seconds() / 60, 2)


def csat_summary(
    tenant: Tenant, *, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> dict[str, Any]:
    """Moyenne, distribution (compte par note 1-5), nombre de reponses,
    taux de reponse (reponses / tickets resolus-ou-clotures de la
    periode)."""
    tickets = _date_filtered_tickets(tenant, date_from, date_to)
    resolved_or_closed_count = tickets.filter(state__in=RESOLVED_OR_CLOSED_STATES).count()
    responses = HlpCsatResponse.objects.filter(ticket__in=tickets)

    response_count = responses.count()
    average_score = responses.aggregate(avg=Avg("score"))["avg"]
    distribution: dict[str, int] = {str(score): 0 for score in range(1, 6)}
    for row in responses.values("score").annotate(count=Count("id")):
        distribution[str(row["score"])] = row["count"]
    response_rate = (response_count / resolved_or_closed_count) if resolved_or_closed_count else 0.0

    return {
        "average_score": average_score,
        "score_distribution": distribution,
        "response_count": response_count,
        "resolved_or_closed_count": resolved_or_closed_count,
        "response_rate": response_rate,
    }


def _ticket_metrics_by_group(
    queryset: QuerySet[HlpTicket], group_field: str
) -> list[dict[str, Any]]:
    """Agregation brute partagee (cf. docstring de tete de module) : un
    ticket sans `group_field` renseigne (ex. non assigne / sans equipe) est
    exclu par l'APPELANT avant d'atteindre ce helper (`.exclude(
    <group_field>__isnull=True)`), jamais filtre ici — le helper reste
    volontairement ignorant du sens metier du regroupement."""
    time_to_first_response = ExpressionWrapper(
        F("first_responded_at") - F("created_at"), output_field=DurationField()
    )
    time_to_resolution = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )
    return list(
        queryset.values(group_field).annotate(
            ticket_count=Count("id"),
            resolved_or_closed_count=Count("id", filter=Q(state__in=RESOLVED_OR_CLOSED_STATES)),
            avg_first_response=Avg(
                time_to_first_response, filter=Q(first_responded_at__isnull=False)
            ),
            avg_resolution=Avg(time_to_resolution, filter=Q(resolved_at__isnull=False)),
        )
    )


def _format_group_row(
    row: dict[str, Any], group_field: str, labels: dict[Any, str]
) -> dict[str, Any]:
    group_id = row[group_field]
    ticket_count: int = row["ticket_count"]
    resolved_count: int = row["resolved_or_closed_count"]
    resolution_rate = (resolved_count / ticket_count) if ticket_count else 0.0
    return {
        f"{group_field}_id": str(group_id),
        f"{group_field}_label": labels.get(group_id, str(group_id)),
        "ticket_count": ticket_count,
        "resolved_or_closed_count": resolved_count,
        "resolution_rate": resolution_rate,
        "avg_first_response_minutes": _duration_to_minutes(row["avg_first_response"]),
        "avg_resolution_minutes": _duration_to_minutes(row["avg_resolution"]),
    }


def agent_performance_report(
    tenant: Tenant, *, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> list[dict[str, Any]]:
    """Une ligne par agent (`assignee` distinct sur les tickets de la
    periode) : nombre de tickets assignes, taux de resolution, duree
    moyenne premiere-reponse/resolution (uniquement sur les tickets ou les
    deux horodatages concernes sont renseignes, cf. `Avg(..., filter=...)`
    ci-dessus)."""
    tickets = _date_filtered_tickets(tenant, date_from, date_to).exclude(assignee__isnull=True)
    rows = _ticket_metrics_by_group(tickets, "assignee")
    agent_emails = dict(
        User.objects.filter(id__in=[row["assignee"] for row in rows]).values_list("id", "email")
    )
    return [_format_group_row(row, "assignee", agent_emails) for row in rows]


def team_benchmark_report(
    tenant: Tenant, *, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> list[dict[str, Any]]:
    """Meme regroupement que `agent_performance_report` mais par `team` —
    satisfait « Analytics de performance agent + benchmarking d'equipe »
    (plan, section modeles) SANS aucun nouveau modele `AgentMetric`/
    `TeamBenchmark`."""
    tickets = _date_filtered_tickets(tenant, date_from, date_to).exclude(team__isnull=True)
    rows = _ticket_metrics_by_group(tickets, "team")
    team_names = dict(
        HlpTeam.objects.filter(id__in=[row["team"] for row in rows]).values_list("id", "name")
    )
    return [_format_group_row(row, "team", team_names) for row in rows]


def sla_compliance_report(
    tenant: Tenant, *, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> dict[str, Any]:
    """Total de tickets avec une politique SLA sur la periode, nombre de
    breches (via `HlpSlaBreach`, reparti par `breach_type`), taux de
    conformite. **Calcul honnete, jamais artificiellement plafonne** : un
    ticket peut porter DEUX breches distinctes (premiere-reponse ET
    resolution, cf. `HlpSlaBreach.UniqueConstraint(ticket, breach_type)`),
    `compliance_rate` peut donc descendre sous 0 si les breches depassent le
    nombre de tickets — un signal reel (SLA structurellement intenable pour
    la periode), pas une anomalie a masquer en le forcant a 0 (disclosed
    explicitement, cf. plan : « actually just compute the rate honestly,
    don't force it to look good »)."""
    tickets_with_sla = _date_filtered_tickets(tenant, date_from, date_to).exclude(
        sla_policy__isnull=True
    )
    total = tickets_with_sla.count()
    breaches = HlpSlaBreach.objects.filter(ticket__in=tickets_with_sla)
    breach_count = breaches.count()
    breaches_by_type: dict[str, int] = {
        code: 0 for code, _label in HlpSlaBreach.BREACH_TYPE_CHOICES
    }
    for row in breaches.values("breach_type").annotate(count=Count("id")):
        breaches_by_type[row["breach_type"]] = row["count"]
    compliance_rate = (1 - breach_count / total) if total else None

    return {
        "total_tickets_with_sla": total,
        "breach_count": breach_count,
        "breaches_by_type": breaches_by_type,
        "compliance_rate": compliance_rate,
    }
