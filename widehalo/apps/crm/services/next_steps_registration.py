"""C-3 — les suites possibles d'une opportunite.

**Le CRM est le seul des quatre modules dont les etapes ne sont pas dans
le code.** Elles vivent en base (`CrmStage`), ordonnees par `sequence`, et
changent d'une societe a l'autre : un pipeline configurable est
precisement ce que CRM-4 a livre. Aucune introspection de machine a etats
ne peut donc repondre ici, et c'est la troisieme raison d'etre du
registre.

**Le pipeline PROPOSE, il ne contraint pas.** `move_lead_to_stage`
accepte n'importe quelle etape du pipeline : rien n'oblige a les parcourir
dans l'ordre. Ce module rend donc l'etape SUIVANTE par `sequence` comme
suite naturelle, et les issues terminales (gagne / perdu) comme suites
possibles a tout moment — ce qui est la realite du metier : une affaire se
perd a n'importe quelle etape.

`requires_reason` est reporte dans le libelle : une etape qui exige un
motif doit le dire AVANT le clic, sinon l'utilisateur decouvre le champ
obligatoire au refus."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.next_steps import NextStep, register_next_steps
from apps.crm.models import CrmStage

_WRITE = "crm.change_crmlead"


def _lead_steps(instance: Any, user: User) -> list[NextStep]:
    if not user.has_perm(_WRITE):
        return []
    etape = instance.stage
    if etape is None:
        return []

    etapes = CrmStage.objects.filter(pipeline_id=etape.pipeline_id).order_by("sequence")
    suites: list[NextStep] = []

    suivante = etapes.filter(sequence__gt=etape.sequence, is_won=False, is_lost=False).first()
    if suivante is not None:
        suites.append(
            NextStep(str(suivante.id), _("Passer à « %(etape)s »") % {"etape": suivante.name})
        )

    # Les issues terminales restent atteignables depuis n'importe quelle
    # etape : une affaire se gagne ou se perd sans parcourir la suite.
    for terminale in etapes.filter(is_won=True) | etapes.filter(is_lost=True):
        if terminale.id == etape.id:
            continue
        libelle = _("Marquer « %(etape)s »") % {"etape": terminale.name}
        if terminale.requires_reason:
            libelle = _("%(libelle)s (motif requis)") % {"libelle": libelle}
        suites.append(NextStep(str(terminale.id), libelle))

    return suites


def register() -> None:
    register_next_steps("crm.CrmLead", _lead_steps)
