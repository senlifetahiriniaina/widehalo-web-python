"""L0-4 — ecran d'exploitation de l'ordonnanceur.

Un registre que personne ne peut regarder est un registre qu'on cesse de
croire. L'ecran repond aux trois questions que se pose l'exploitant devant
une commande periodique : a-t-elle tourne, combien de temps, et quand
repasse-t-elle ?

Il repond aussi a une quatrieme, propre a ce depot : la commande est-elle
seulement PLANIFIEE ? Une commande declaree au registre mais absente de
l'ordonnanceur (`sync_scheduled_commands` non rejouee apres la livraison qui
l'a ajoutee) ne tourne pas — c'est exactement le defaut d'origine, dix-neuf
commandes justes que rien n'appelait, et il fallait qu'il soit visible plutot
que deductible.

Garde `is_superuser` STRICT, comme `backup_admin` : les planifications sont
globales et non rattachees a un tenant ; un administrateur de societe n'a pas
a voir l'etat d'exploitation de l'instance entiere."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.tasks import scheduled_command_status


@login_required
def scheduled_commands_view(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        return HttpResponse(status=403)

    rows = scheduled_command_status()
    return render(
        request,
        "scheduled_commands.html",
        {
            "rows": rows,
            "unscheduled_count": sum(1 for row in rows if not row["is_scheduled"]),
            "failed_count": sum(1 for row in rows if row["success"] is False),
        },
    )
