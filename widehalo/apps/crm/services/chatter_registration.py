"""L4 (CRM-1) — garde de perimetre du chatter sur `CrmLead`.

**Pourquoi cette garde est indispensable, et pas un raffinement.** La vue
generique du chatter (`apps.core.views.chatter._can_view_chatter_object`)
retombe, faute de garde enregistree, sur la permission de MODELE :
`user.has_perm("crm.view_crmlead")`. Or RG-CRM-5 n'est pas une regle de
modele mais de PERIMETRE — « un commercial ne voit que ses propres
opportunites, un resp_commercial celles de son equipe » — et tout
commercial porte `crm.view_crmlead`.

Cabler `<c-chatter>` sur `CrmLead` SANS enregistrer cette garde aurait donc
rouvert, sur le fil de discussion, exactement la faille refermee aux
bloquants (4/4) sur l'API : lire — et ecrire — la conversation attachee a
l'opportunite d'un collegue par simple connaissance de son UUID. Le
chatter n'est pas un ecran secondaire : il porte les notes internes, les
motifs de perte et l'historique commercial.

La garde delegue a `scope_leads_for_user`, jamais a une liste de roles
recopiee : une regle de perimetre dupliquee est une regle qui divergera.
Meme patron d'auto-enregistrement que `payroll.services.
chatter_registration` (seul precedent du depot), appele depuis
`apps.py::ready()`."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from apps.core.services.chatter_guard_registry import register_object_guard

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.core.models.base import BaseModel


def register_chatter_guards() -> None:
    from apps.crm.models import CrmLead
    from apps.crm.services.scoping import scope_leads_for_user

    def _guard(request: HttpRequest, instance: BaseModel) -> bool:
        lead = cast(CrmLead, instance)
        return scope_leads_for_user(CrmLead.objects.filter(pk=lead.pk), request.user).exists()  # type: ignore[arg-type]

    register_object_guard("crm", "crmlead", _guard)
