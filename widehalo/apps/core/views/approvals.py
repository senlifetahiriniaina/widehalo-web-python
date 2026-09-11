"""D-B — l'ecran « Mes validations ».

**Pourquoi il fallait le construire, et pourquoi c'etait bloquant.**
`validate_invoice` cree une demande d'approbation et refuse la validation
des qu'une facture depasse le palier
(`apps/accounting/services/invoices.py:292-309`), et les trois paliers sont
semes EN PRODUCTION pour toute societe
(`apps/accounting/management/commands/seed_accounting.py:121`). Or aucun
ecran du produit ne decidait une demande : seul
`POST /api/v1/approvals/{id}/decide` le pouvait. L'exploitant cliquait
« Valider », lisait « Validation en attente d'approbation (comptable) », et
**la facture restait bloquee definitivement**. C'est l'operation centrale du
module comptable.

`pending_for_user` existe depuis le lot 1 et n'avait qu'un seul appelant de
production — l'API. Il en a enfin un d'ecran.

**L'ecran ne reimplemente rien.** Il passe par `decide_and_propagate`, le
meme point d'entree que l'API : meme controle d'eligibilite, meme effet de
bord metier apres decision. Deux chemins de decision qui divergeraient
finiraient par ne pas produire le meme resultat.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest
from apps.core.services import approvals
from apps.core.services.document_screens import resolve_document_url
from apps.core.services.role_hierarchy import superieur_de


def _piece(demande: ApprovalRequest) -> dict[str, Any]:
    """La piece concernee : son libelle et son lien, quand elle en a un.

    Une demande peut porter sur un objet dont le module n'a pas d'ecran de
    detail — une ligne d'import, par exemple. L'ecran le DIT au lieu de
    rendre un lien mort : meme regle qu'au journal des echanges (T8)."""
    modele = demande.content_type.model_class()
    if modele is None:
        return {"libelle": demande.content_type.model, "url": None}
    return {
        "libelle": modele._meta.verbose_name,
        "url": resolve_document_url(modele._meta.label, demande.object_id),
    }


@login_required
def approvals_page(request: HttpRequest) -> HttpResponse:
    utilisateur = cast(User, request.user)
    erreur = None

    if request.method == "POST":
        demande = ApprovalRequest.objects.filter(id=request.POST.get("request_id", "")).first()
        if demande is None:
            # `ApprovalRequest.objects` est un `TenantManager` : une demande
            # d'une autre societe n'existe pas pour cette requete. On le dit
            # comme une absence, jamais comme une erreur technique.
            erreur = _("Cette demande n'existe pas pour cette société.")
        else:
            try:
                approvals.decide_and_propagate(
                    demande,
                    utilisateur,
                    approved=request.POST.get("action") == "approve",
                    comment=request.POST.get("comment", ""),
                )
            except PermissionDenied:
                erreur = _(
                    "Vous n'êtes pas approbateur de cette demande : elle revient à son "
                    "rôle titulaire, ou à son supérieur après le délai d'escalade."
                )
            else:
                return redirect("approvals")

    demandes = [
        {
            "objet": demande,
            "piece": _piece(demande),
            "superieur": superieur_de(demande.rule.approver_role),
        }
        for demande in approvals.pending_for_user(utilisateur).select_related(
            "rule", "requested_by", "content_type"
        )
    ]
    return render(
        request,
        "core/approvals.html",
        {"demandes": demandes, "error": erreur},
    )
