"""F-1 — la file d'e-factures, et le geste qui la rejoue.

**Ce que la 0.1.8 a mesuré, et pourquoi elle a reclassé EFA-3 en
partielle.** Le critère demande que la file se rejoue « dans l'ordre
chronologique, sans perte, sans doublon » le jour où le raccordement
s'ouvre. Le moteur existe depuis T4, il est correct et il est testé. **Ses
trois fonctions n'avaient aucun appelant de production** : ni écran, ni
commande d'administration, ni tâche planifiée. Personne ne pouvait
déclencher le rejeu — un critère tenu par du code que rien n'invoque n'est
pas tenu.

**Le rejeu est un geste d'EXPLOITATION, jamais une tâche de fond.** Ouvrir
un raccordement fiscal est une décision, et le cahier le dit : « sans
intervention manuelle autre que la confirmation initiale ». La
confirmation, c'est l'activation — et c'est cet écran qui la porte. Rien
ne part la nuit de soi-même : ce serait transmettre à une administration
sans que personne ne l'ait décidé.

**L'écran ne présente aucune erreur sur l'attente**, parce que EFA-2
l'interdit : une pièce qui attend une destination est un état normal du
mode dégradé, pas une panne.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.services.einvoice_replay import (
    pending_submissions,
    replay_pending_submissions,
)
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.tenant_web import resolve_tenant


@login_required
@screen_permission("accounting.view_accmove")
def einvoice_queue(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""
    rapport = None

    if request.method == "POST":
        # Rejouer SOUMET des pièces à une administration : c'est une
        # écriture sur l'axe fiscal de chaque facture, jamais une lecture.
        refus = screen_forbidden(request, "accounting.change_accmove")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "replay":
                rapport = replay_pending_submissions(tenant)
            elif action == "open_link":
                from apps.accounting.services.einvoice_replay import open_fiscal_link

                rapport = open_fiscal_link(tenant)
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            # Le rapport chiffré doit RESTER à l'écran : c'est lui qui dit
            # ce que la passe a fait, et une redirection l'effacerait.
            pass

    contexte: dict[str, Any] = {
        "en_attente": pending_submissions(tenant),
        "rapport": rapport,
        "error": erreur,
    }
    return render(request, "accounting/einvoice_queue.html", contexte)


@login_required
@screen_permission("accounting.change_accmove")
def einvoice_replay_now(request: HttpRequest) -> HttpResponse:
    """Point d'entrée POST-only, pour un déclenchement depuis un autre écran.

    La garde d'écriture est AU DÉCORATEUR : cette vue n'existe que pour
    écrire, et un rôle en lecture seule ne doit pas l'atteindre du tout."""
    if request.method != "POST":
        return HttpResponse(status=405)
    replay_pending_submissions(resolve_tenant(request))
    return redirect("accounting:einvoice_queue")
