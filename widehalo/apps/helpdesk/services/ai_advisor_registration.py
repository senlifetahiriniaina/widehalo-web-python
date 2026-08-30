"""AI7 : auto-enregistrement d'une regle d'advisor d'actions DETERMINISTE
du module `helpdesk` dans `core.services.advisor_rule_registry`, appele
depuis `apps.py::ready()` — meme patron exact que `apps.purchase.services.
ai_advisor_registration._suggest_incident_followup` deja etabli dans ce
chantier (« un volume d'incidents ouverts au-dela d'un seuil trivial
justifie de recommander d'automatiser leur suivi via une action deja
enregistree dans `core.services.automation_registry` »).

**Adaptateur mince, pas une nouvelle regle metier** : `_advise_on_helpdesk`
compte les tickets ESCALADES recents (fenetre glissante) groupes par
`ticket_type` — une RECURRENCE d'un meme type de ticket escalade
(`>= _ESCALATED_RECURRENCE_THRESHOLD` occurrences) suggere que la source
de l'incident (deja rattachee via `content_type`/`object_id`, cf. plan
« Extension actee... ») pourrait etre creee automatiquement plutot que
manuellement a chaque fois — rapprochement DIRECT avec l'action
`helpdesk.create_ticket_from_event` DEJA enregistree (cf. `services/
automation_registration.py`), exactement l'exemple cite par le plan
AI7 : "une action deja automatisable est une candidate naturelle de
suggestion"."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule

_ESCALATED_RECURRENCE_THRESHOLD = 3
_RECENT_WINDOW_DAYS = 30


def _advise_on_helpdesk(
    tenant_id: str, action: str, role_code: str
) -> list[RecommendationCandidate]:
    del action, role_code  # pertinent quel que soit l'ecran/role helpdesk en cours
    from apps.helpdesk.models import HlpTicket

    since = timezone.now() - timedelta(days=_RECENT_WINDOW_DAYS)
    rows = (
        HlpTicket.objects.filter(
            tenant_id=tenant_id,
            state=HlpTicket.STATE_ESCALATED,
            ticket_type__isnull=False,
            created_at__gte=since,
        )
        .values("ticket_type_id", "ticket_type__label")
        .annotate(count=Count("id"))
        .filter(count__gte=_ESCALATED_RECURRENCE_THRESHOLD)
        .order_by("-count")
    )
    if not rows:
        return []

    return [
        RecommendationCandidate(
            label=gettext(
                "%(count)s ticket(s) de type « %(type)s » escalade(s) sur les "
                "%(days)s derniers jours — envisagez d'automatiser leur creation "
                "depuis l'evenement source"
            )
            % {
                "count": row["count"],
                "type": row["ticket_type__label"],
                "days": _RECENT_WINDOW_DAYS,
            },
            target_module="helpdesk",
            target_action_code="helpdesk.create_ticket_from_event",
        )
        for row in rows
    ]


def register_ai_advisor_rules() -> None:
    register_advisor_rule(
        "helpdesk.escalation_advisor",
        module="helpdesk",
        label="Recurrence de tickets escalades par type",
        function=_advise_on_helpdesk,
    )
