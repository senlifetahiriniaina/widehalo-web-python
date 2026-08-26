"""Deplacement d'une opportunite le long des etapes de son pipeline
(§5.2.4). Les etapes elles-memes (et leurs probabilites) sont
PARAMETRABLES par pipeline (`CrmStage.sequence`/`probability`/`is_won`/
`is_lost`) — il n'y a donc pas de machine a etats a enum fixe ici : la
"transition" est un simple changement de `CrmLead.stage`, avec les regles
de gestion appliquees en service (RG-CRM-6)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.crm.models import CrmLead, CrmLostReason, CrmStage


def move_lead_to_stage(
    lead: CrmLead,
    stage: CrmStage,
    *,
    lost_reason: CrmLostReason | None = None,
    comment: str = "",
) -> CrmLead:
    if lead.stage.is_won or lead.stage.is_lost:
        raise ValidationError(_("Une opportunite gagnee ou perdue ne peut plus changer d'etape."))
    if stage.pipeline_id != lead.pipeline_id:
        raise ValidationError(_("L'etape cible n'appartient pas au pipeline de l'opportunite."))

    # RG-CRM-6 : motif + commentaire obligatoires pour passer en etape "perdue".
    if stage.is_lost or stage.requires_reason:
        if lost_reason is None or not comment:
            raise ValidationError(_("Motif et commentaire obligatoires pour marquer une perte"))
        lead.lost_reason = lost_reason
        lead.lost_comment = comment
        lead.lost_at = timezone.now()
    elif stage.is_won:
        lead.won_at = timezone.now()

    lead.stage = stage
    lead.probability = stage.probability
    lead.save(
        update_fields=["stage", "probability", "lost_reason", "lost_comment", "lost_at", "won_at"]
    )
    return lead
