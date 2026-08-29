"""Ecran de configuration (parametrage) du module `projects` (PJ7) —
meme convention deja etablie par `apps.accounting.views_config` : un seul
fichier `views_config.py` dedie, un `config_index` hub, une page
liste+creation par entite de parametrage. `projects` n'a pour l'instant
QU'UNE seule entite de parametrage (`PrjCustomFieldDefinition`) — pas de
sous-menu `config_index` necessaire pour une seule page, mais le fichier
est cree des maintenant pour accueillir un futur hub si d'autres ecrans de
parametrage `projects` apparaissent (portail invite PJ14, automatisations
PJ11...).

**RBAC** : cette permission est PERSONNALISEE et restreinte a
`admin`/`direction` cote API (`projects.manage_prjcustomfielddefinition`,
cf. `apps.projects.api`) — l'ecran HTMX lui-meme ne fait que
`@login_required`, meme discipline que tous les autres ecrans HTMX de ce
depot (le controle N2 fin est applique cote service/API, cf. disclosure
similaire dans `apps.projects.views::project_billing`)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.views.tenant_web import resolve_tenant
from apps.projects.models import PrjCustomFieldDefinition


@login_required
def config_custom_fields(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            validation_rule: dict[str, Any] = {}
            if request.POST.get("required"):
                validation_rule["required"] = True
            if request.POST.get("choices"):
                validation_rule["choices"] = [
                    choice.strip()
                    for choice in request.POST["choices"].split(",")
                    if choice.strip()
                ]
            if request.POST.get("min"):
                validation_rule["min"] = float(request.POST["min"])
            if request.POST.get("max"):
                validation_rule["max"] = float(request.POST["max"])
            PrjCustomFieldDefinition.objects.create(
                tenant=tenant,
                entity_type=request.POST.get("entity_type", PrjCustomFieldDefinition.ENTITY_TASK),
                field_key=request.POST.get("field_key", ""),
                field_label=request.POST.get("field_label", ""),
                field_type=request.POST.get("field_type", PrjCustomFieldDefinition.FIELD_TYPE_TEXT),
                validation_rule=validation_rule,
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    definitions = PrjCustomFieldDefinition.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "projects/config_custom_fields.html",
        {
            "definitions": definitions,
            "entity_choices": PrjCustomFieldDefinition.ENTITY_CHOICES,
            "field_type_choices": PrjCustomFieldDefinition.FIELD_TYPE_CHOICES,
            "error": error,
        },
    )
