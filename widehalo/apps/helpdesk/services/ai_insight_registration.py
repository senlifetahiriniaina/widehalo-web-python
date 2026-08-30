"""AI5 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `helpdesk` dans `core.services.insight_source_registry`, appele
depuis `apps.py::ready()` — meme patron exact que `apps.presence.services.
ai_insight_registration._absence_trend` deja etabli dans ce chantier
(comparaison de deux fenetres glissantes de 7 jours consecutives).

**Deviation disclosed par rapport a une lecture litterale du plan**
(« compare open-ticket count now vs. some prior window ») : `helpdesk` ne
conserve AUCUN historique d'etat (pas de snapshot quotidien du nombre de
tickets ouverts) — reconstruire un "nombre de tickets ouverts il y a 7
jours" exigerait soit un nouveau modele d'audit (hors perimetre HD5, cf.
plan section modeles : aucun nouveau modele pour ce chantier), soit une
approximation invraisemblable a partir des seuls horodatages actuels.
**Metrique retenue a la place, honnetement calculable depuis les
horodatages DEJA portes par `HlpTicket`** : la variation NETTE du backlog
sur une fenetre (`crees - resolus` dans la fenetre, `resolved_at` faisant
foi pour une resolution) comparee entre la semaine courante et la semaine
precedente — memes deux fenetres de 7 jours consecutives que `presence.
absence_trend`, un signal de tendance de backlog authentique sans jamais
supposer un etat passe non enregistre."""

from __future__ import annotations

import datetime as dt

from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source

_WINDOW_DAYS = 7
# Seuil de croissance NETTE du backlog (tickets crees moins tickets
# resolus) entre les deux fenetres pour declencher l'insight — choisi
# arbitrairement comme un volume "non trivial" (3 tickets de plus qu'une
# semaine normale), disclosed comme point de depart ajustable, memes
# discipline "insight, pas du bruit" que `presence.absence_trend` (qui
# exige une hausse stricte, jamais un plateau/une baisse).
_GROWTH_THRESHOLD = 3


def _net_backlog_change(tenant_id: str, window_start: dt.datetime, window_end: dt.datetime) -> int:
    from apps.helpdesk.models import HlpTicket

    created = HlpTicket.objects.filter(
        tenant_id=tenant_id, created_at__gte=window_start, created_at__lt=window_end
    ).count()
    resolved = HlpTicket.objects.filter(
        tenant_id=tenant_id, resolved_at__gte=window_start, resolved_at__lt=window_end
    ).count()
    return created - resolved


def _backlog_trend_insight(tenant_id: str) -> list[InsightCandidate]:
    from django.utils import timezone

    now = timezone.now()
    current_start = now - dt.timedelta(days=_WINDOW_DAYS)
    previous_start = current_start - dt.timedelta(days=_WINDOW_DAYS)

    current_net = _net_backlog_change(tenant_id, current_start, now)
    previous_net = _net_backlog_change(tenant_id, previous_start, current_start)
    growth = current_net - previous_net

    # Signal remonte uniquement en cas de croissance REELLE et non triviale
    # du backlog net — jamais un insight quotidien sur une variation stable
    # ou une amelioration.
    if growth < _GROWTH_THRESHOLD:
        return []

    return [
        InsightCandidate(
            category="helpdesk",
            title="Croissance du backlog de tickets",
            body=(
                f"Le backlog net (tickets crees moins tickets resolus) sur les "
                f"{_WINDOW_DAYS} derniers jours est de {current_net}, contre "
                f"{previous_net} la semaine precedente — une hausse de {growth} "
                f"ticket(s) non resolu(s) net(s)."
            ),
            source_modules=["helpdesk"],
        )
    ]


def register_ai_insight_sources() -> None:
    register_insight_source(
        "helpdesk.ticket_backlog_trend",
        module="helpdesk",
        label="Tendance du backlog de tickets",
        function=_backlog_trend_insight,
    )
