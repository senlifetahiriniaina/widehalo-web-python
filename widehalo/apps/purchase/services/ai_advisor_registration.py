"""AI7 : auto-enregistrement d'une regle d'advisor d'actions DETERMINISTE
du module `purchase` dans `core.services.advisor_rule_registry`, appele
depuis `apps.py::ready()` — meme patron que `ai_anomaly_registration.
register_ai_anomaly_checks()`/`ai_context_registration.
register_ai_context()` deja etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_suggest_incident_
followup` compte les `PurCri` (compte rendu d'incident achats, PU7) encore
`STATE_DRAFT` (ouverts) du tenant — un volume d'incidents fournisseur
ouverts au-dela d'un seuil trivial (>= 3) justifie de recommander
d'automatiser leur suivi via l'action `purchase.open_incident` DEJA
enregistree dans `core.services.automation_registry` (AUTO3, cf.
`services/automation_registration.py`) — un rapprochement DIRECT avec
cette action deja whitelistee, jamais une nouvelle capacite construite ici
(exactement l'exemple cite par le plan : "une action deja automatisable
est une candidate naturelle de suggestion")."""

from __future__ import annotations

from django.utils.translation import gettext

from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule

_OPEN_INCIDENT_THRESHOLD = 3


def _suggest_incident_followup(
    tenant_id: str, action: str, role_code: str
) -> list[RecommendationCandidate]:
    del action, role_code  # pertinent quel que soit l'ecran/role d'achats en cours
    from apps.purchase.models import PurCri

    open_count = PurCri.objects.filter(tenant_id=tenant_id, state=PurCri.STATE_DRAFT).count()
    if open_count < _OPEN_INCIDENT_THRESHOLD:
        return []

    return [
        RecommendationCandidate(
            label=gettext(
                "%(count)s litige(s) fournisseur ouvert(s) — envisagez d'automatiser "
                "leur ouverture/suivi"
            )
            % {"count": open_count},
            target_module="purchase",
            target_action_code="purchase.open_incident",
        )
    ]


def register_advisor_rules() -> None:
    register_advisor_rule(
        "purchase.incident_followup",
        module="purchase",
        label="Suivi des litiges fournisseur ouverts",
        function=_suggest_incident_followup,
    )
