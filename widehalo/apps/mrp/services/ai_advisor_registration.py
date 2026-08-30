"""AI7 : auto-enregistrement d'une regle d'advisor d'actions DETERMINISTE
du module `mrp` dans `core.services.advisor_rule_registry`, appele depuis
`apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()`/`automation_registration.register_actions()` deja
etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_suggest_
conformity_followup` compte les `MrpCri` de type `TYPE_QUALITY_INCIDENT`
encore `STATE_DRAFT` (ouverts) du tenant — un volume d'incidents qualite
ouverts au-dela d'un seuil trivial (>= 3) justifie de recommander
d'automatiser leur ouverture via l'action `mrp.open_conformity_incident`
DEJA enregistree dans `core.services.automation_registry` (AUTO3, cf.
`services/automation_registration.py`) — meme raisonnement exact que
`apps.purchase.services.ai_advisor_registration` (rapprochement DIRECT
avec une action deja whitelistee, jamais une nouvelle capacite)."""

from __future__ import annotations

from django.utils.translation import gettext

from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule

_OPEN_INCIDENT_THRESHOLD = 3


def _suggest_conformity_followup(
    tenant_id: str, action: str, role_code: str
) -> list[RecommendationCandidate]:
    del action, role_code  # pertinent quel que soit l'ecran/role de production en cours
    from apps.mrp.models import MrpCri

    open_count = MrpCri.objects.filter(
        tenant_id=tenant_id,
        type=MrpCri.TYPE_QUALITY_INCIDENT,
        state=MrpCri.STATE_DRAFT,
    ).count()
    if open_count < _OPEN_INCIDENT_THRESHOLD:
        return []

    return [
        RecommendationCandidate(
            label=gettext(
                "%(count)s incident(s) de conformite ouvert(s) — envisagez d'automatiser "
                "leur ouverture/suivi"
            )
            % {"count": open_count},
            target_module="mrp",
            target_action_code="mrp.open_conformity_incident",
        )
    ]


def register_advisor_rules() -> None:
    register_advisor_rule(
        "mrp.conformity_incident_followup",
        module="mrp",
        label="Suivi des incidents de conformite ouverts",
        function=_suggest_conformity_followup,
    )
