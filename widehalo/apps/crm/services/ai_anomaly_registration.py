"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `crm` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_stagnant_
opportunities` ne fait QUE surfacer des champs DEJA portes par `CrmLead`/
`CrmActivity` (`won_at`/`lost_at`/`CrmActivity.created_at`) — aucun nouveau
calcul introduit ici.

**Deviation disclosed par rapport a une lecture litterale du plan**
(« CrmLead dans le meme stage depuis plus de N jours ») : `CrmLead` ne
porte AUCUN horodatage d'entree de stage (`stage_changed_at` n'existe pas,
seul `updated_at` existe et est touche par TOUTE modification du lead, pas
seulement un changement d'etape — l'utiliser reviendrait a une fausse
precision). **Metrique retenue a la place, honnetement calculable depuis
les donnees existantes** : une opportunite encore ouverte
(`won_at`/`lost_at` tous deux `NULL`) sans AUCUNE `CrmActivity` enregistree
depuis `_STAGNANT_WINDOW_DAYS` jours (ou, si aucune activite n'a jamais ete
enregistree, depuis sa creation) — un signal de stagnation authentique et
directement actionnable (« relancer ce lead »), sans supposer un
horodatage de changement d'etape qui n'est pas trace."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)


def _check_stagnant_opportunities(tenant_id: str) -> list[AnomalyCandidate]:
    """Opportunites sans activite depuis plus de N jours.

    **N est desormais parametrable** (CRM-4, L4) : il vient de
    `CrmPipeline.stagnant_after_days`, et non plus d'une constante de
    module que seule une livraison pouvait changer. Le seuil est lu PAR
    PIPELINE — deux cycles de vente de duree differente cohabitent dans un
    meme tenant."""
    from apps.crm.services.stagnation import stagnant_leads

    candidates: list[AnomalyCandidate] = []
    for lead, days_stagnant, window in stagnant_leads(tenant_id):
        severity = SEVERITY_HIGH if days_stagnant >= window * 2 else SEVERITY_MEDIUM
        candidates.append(
            AnomalyCandidate(
                content_type_label="crm.crmlead",
                object_id=str(lead.id),
                severity=severity,
                description=(
                    f"Opportunite « {lead.name} » (etape « {lead.stage.name} ») sans "
                    f"activite enregistree depuis {days_stagnant} jour(s)."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "crm.stagnant_opportunity",
        module="crm",
        label="Opportunite stagnante (aucune activite recente)",
        function=_check_stagnant_opportunities,
    )
