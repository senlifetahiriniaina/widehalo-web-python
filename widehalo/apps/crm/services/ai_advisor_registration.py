"""INT2 : auto-enregistrement d'une regle d'advisor d'actions DETERMINISTE
du module `crm` dans `core.services.advisor_rule_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.purchase.services.
ai_advisor_registration._suggest_incident_followup` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_advise_on_crm`
reutilise DIRECTEMENT `apps.crm.services.ai_anomaly_registration._check_
stagnant_opportunities` (INT2, meme module) — une opportunite deja
detectee comme stagnante par le registre d'anomalies est une candidate
naturelle de suggestion de relance, rapprochee de l'action
`crm.notify_role_of_opportunity` DEJA enregistree (cf. `services/
automation_registration.py`), exactement l'exemple cite par le plan AI7 :
"une action deja automatisable est une candidate naturelle de
suggestion"."""

from __future__ import annotations

from django.utils.translation import gettext

from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule


def _advise_on_crm(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
    del action, role_code  # pertinent quel que soit l'ecran/role commercial en cours
    from apps.crm.services.ai_anomaly_registration import _check_stagnant_opportunities

    stagnant = _check_stagnant_opportunities(tenant_id)
    if not stagnant:
        return []

    return [
        RecommendationCandidate(
            label=gettext("%(count)s opportunite(s) sans activite recente — envisagez une relance")
            % {"count": len(stagnant)},
            target_module="crm",
            target_action_code="crm.notify_role_of_opportunity",
        )
    ]


def register_ai_advisor_rules() -> None:
    register_advisor_rule(
        "crm.stagnant_opportunity_followup",
        module="crm",
        label="Relance des opportunites stagnantes",
        function=_advise_on_crm,
    )
