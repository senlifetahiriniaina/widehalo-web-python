"""Fil de discussion generique (chatter) -- Sprint 3 / L2 de la refonte UX
(cf. docs/planning/2026-refonte-ux-sprints.md §5). Vue Django classique
(HTMX), pas django-ninja -- meme partition que le reste du depot entre
fragments HTMX et API publique (cf. docs/planning/ECART_ARCHITECTURE.md
§3), meme idiome que `apps.core.views.pages.notifications_bell_fragment`.

**Autorisation par objet (gap detecte lors de la revision complete
Sprints 0-9)** : au-dela du filtre tenant deja assure par `BaseModel`/RLS,
`_can_view_chatter_object` consulte `apps.core.services.
chatter_guard_registry` -- une app peut enregistrer une garde fine par
modele (ex. RG-PAY-9 pour `payroll.PayPayslip`, "l'employe proprietaire OU
un role staff", jamais un simple droit Django par modele) ; a defaut de
garde enregistree, retombe sur `user.has_perm(f"{app_label}.view_{model}")`
-- meme patron que `apps.core.services.search.global_search`."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core.models.base import BaseModel
from apps.core.models.user import User
from apps.core.services.chatter import post_message, thread_for
from apps.core.services.chatter_guard_registry import get_object_guard


def _resolve_instance(app_label: str, model: str, object_id: str) -> BaseModel | None:
    content_type = get_object_or_404(ContentType, app_label=app_label, model=model)
    model_class = content_type.model_class()
    if model_class is None or not issubclass(model_class, BaseModel):
        return None
    return get_object_or_404(model_class, pk=object_id)


def _can_view_chatter_object(
    request: HttpRequest, app_label: str, model: str, instance: BaseModel
) -> bool:
    guard = get_object_guard(app_label, model)
    if guard is not None:
        return guard(request, instance)
    return cast(User, request.user).has_perm(f"{app_label}.view_{model.lower()}")


@login_required
def chatter_thread(
    request: HttpRequest, app_label: str, model: str, object_id: str
) -> HttpResponse:
    """GET : fragment complet (fil + formulaire). POST : poste un
    message/une note puis renvoie le meme fragment rafraichi -- jamais de
    reload complet de la page hote (A.10 du cahier des charges)."""
    instance = _resolve_instance(app_label, model, object_id)
    if instance is None:
        return HttpResponse(status=404)
    if not _can_view_chatter_object(request, app_label, model, instance):
        return HttpResponse(status=403)

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            post_message(
                instance,
                author=cast(User, request.user),
                body=body,
                is_note=request.POST.get("is_note") == "on",
            )
    elif request.method != "GET":
        return HttpResponse(status=405)

    return render(
        request,
        "components/_chatter.html",
        {
            "chatter_app_label": app_label,
            "chatter_model": model,
            "chatter_object_id": object_id,
            "messages_thread": thread_for(instance),
        },
    )
