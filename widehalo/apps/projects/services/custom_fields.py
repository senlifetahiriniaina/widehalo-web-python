"""Validation des champs personnalises (PJ7) — cf. docstring de
`PrjCustomFieldDefinition` pour la structure exacte (documentee comme
"libre") de `validation_rule` selon `field_type`. Fichier separe de
`services/capacity.py` (domaine different : configuration/validation de
schema, pas de capacite d'equipe) mais du meme chantier PJ7.

`validate_custom_fields` est appelee par `services/tasks.py::create_task`
AVANT toute ecriture dans `PrjTask.custom_fields` — jamais une validation
a posteriori qui laisserait une valeur invalide deja persistee."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.projects.models import PrjCustomFieldDefinition

_NUMBER_TYPES = (int, float)


def _validate_one_field(definition: PrjCustomFieldDefinition, values: dict[str, Any]) -> None:
    rule = definition.validation_rule or {}
    key = definition.field_key
    present = key in values and values[key] is not None
    if not present:
        if rule.get("required"):
            raise ValidationError(_("Champ personnalise '%(key)s' requis.") % {"key": key})
        return

    value = values[key]
    field_type = definition.field_type

    if field_type == PrjCustomFieldDefinition.FIELD_TYPE_TEXT:
        if not isinstance(value, str):
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre du texte.") % {"key": key}
            )
    elif field_type == PrjCustomFieldDefinition.FIELD_TYPE_BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre un booleen.") % {"key": key}
            )
    elif field_type == PrjCustomFieldDefinition.FIELD_TYPE_DATE:
        if isinstance(value, dt.date):
            pass
        elif isinstance(value, str):
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError(
                    _("Champ personnalise '%(key)s' doit etre une date ISO (AAAA-MM-JJ).")
                    % {"key": key}
                ) from exc
        else:
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre une date.") % {"key": key}
            )
    elif field_type == PrjCustomFieldDefinition.FIELD_TYPE_NUMBER:
        if isinstance(value, bool) or not isinstance(value, _NUMBER_TYPES):
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre un nombre.") % {"key": key}
            )
        minimum = rule.get("min")
        maximum = rule.get("max")
        if minimum is not None and value < minimum:
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre >= %(min)s.")
                % {"key": key, "min": minimum}
            )
        if maximum is not None and value > maximum:
            raise ValidationError(
                _("Champ personnalise '%(key)s' doit etre <= %(max)s.")
                % {"key": key, "max": maximum}
            )
    elif field_type == PrjCustomFieldDefinition.FIELD_TYPE_CHOICE:
        choices = rule.get("choices") or []
        if value not in choices:
            raise ValidationError(
                _("Champ personnalise '%(key)s' : valeur '%(value)s' hors des choix autorises.")
                % {"key": key, "value": value}
            )


def validate_custom_fields(tenant: Tenant, entity_type: str, values: dict[str, Any] | None) -> None:
    """Verifie `values` contre TOUTES les `PrjCustomFieldDefinition` actives
    du tenant courant pour `entity_type` (`PrjCustomFieldDefinition.
    ENTITY_PROJECT`/`ENTITY_TASK`). Leve `ValidationError` avec un message
    explicite sur le PREMIER champ invalide trouve (ordre `field_key`,
    deterministe, cf. `Meta.ordering` de `PrjCustomFieldDefinition`) —
    jamais une agregation silencieuse de toutes les erreurs a la fois
    (suffisant pour ce garde-fou de creation, meme discipline que le reste
    de ce module : un message actionnable plutot qu'une liste generique).

    `values=None` est traite comme `{}` (aucune valeur fournie) — permet
    d'appeler cette fonction inconditionnellement depuis `create_task`
    meme quand l'appelant ne passe pas de `custom_fields`."""
    values = values or {}
    definitions = PrjCustomFieldDefinition.objects.filter(
        tenant=tenant, entity_type=entity_type, is_active=True
    ).order_by("field_key")
    for definition in definitions:
        _validate_one_field(definition, values)
