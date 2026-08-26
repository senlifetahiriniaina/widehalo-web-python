"""Bac a sable par clonage : copie anonymisee d'un tenant pour tests/
formation, avec expiration automatique. Implementation simple, non
optimisee pour de gros volumes (cf. simplifications assumees du lot) —
suffisante tant que le volume de donnees reel n'existe pas encore."""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta

from django.apps import apps as django_apps
from django.utils import timezone

from apps.core.db.uuid7 import uuid7
from apps.core.models.base import BaseModel
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

DEFAULT_EXPIRY_DAYS = 30

# Champs consideres comme des donnees personnelles a anonymiser lors du
# clonage — remplacement deterministe simple, pas de moteur de regles
# configurable pour ce lot (cf. simplifications assumees).
PII_FIELD_NAMES = {"email", "phone", "first_name", "last_name", "name", "label", "original_name"}


def _anonymize_field_value(field_name: str, index: int) -> str:
    return f"sandbox-{field_name}-{index}"


def clone_tenant_to_sandbox(source: Tenant, expires_in_days: int = DEFAULT_EXPIRY_DAYS) -> Tenant:
    sandbox = Tenant.objects.create(
        # uuid4 (pas uuid7) pour le suffixe : uuid7 est base sur l'horodatage
        # et deux appels rapproches partageraient le meme prefixe tronque.
        code=f"{source.code}-SBX-{uuid.uuid4().hex[:10]}",
        name=f"{source.name} (bac à sable)",
        nif=source.nif,
        country_code=source.country_code,
        base_currency=source.base_currency,
        default_language=source.default_language,
        timezone=source.timezone,
        is_sandbox=True,
        sandbox_source=source,
        sandbox_expires_at=timezone.now() + timedelta(days=expires_in_days),
    )

    # La RLS s'applique aussi a `all_objects` (seul le filtrage cote Django
    # est desactive, pas le controle Postgres) : il faut donc activer le
    # contexte du tenant SOURCE pour lire ses lignes, materialiser les
    # objets en memoire, PUIS activer le contexte du tenant SANDBOX pour
    # les ecrire — les deux contextes ne peuvent pas etre actifs a la fois.
    rows_by_model = {}
    with activate_tenant(source.id):
        for model in django_apps.get_models():
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                continue
            if model._meta.abstract or ".tests." in model.__module__:
                continue
            rows_by_model[model] = list(model.all_objects.filter(tenant=source))

    counter = 0
    with activate_tenant(sandbox.id):
        for rows in rows_by_model.values():
            for obj in rows:
                counter += 1
                clone = copy.copy(obj)
                clone.id = uuid7()
                clone.tenant = sandbox
                clone._state.adding = True

                for field_name in PII_FIELD_NAMES:
                    if hasattr(clone, field_name):
                        setattr(clone, field_name, _anonymize_field_value(field_name, counter))

                clone.save()

    return sandbox


def purge_expired_sandboxes() -> int:
    """Supprime les tenants sandbox expires. `BaseModel.tenant` est en
    PROTECT (garde-fou general contre la suppression accidentelle d'un
    tenant avec des donnees) — on doit donc d'abord vider les donnees
    clonees du sandbox avant de supprimer le tenant lui-meme."""
    expired = list(Tenant.objects.filter(is_sandbox=True, sandbox_expires_at__lte=timezone.now()))

    for sandbox in expired:
        with activate_tenant(sandbox.id):
            for model in django_apps.get_models():
                if not (isinstance(model, type) and issubclass(model, BaseModel)):
                    continue
                if model._meta.abstract:
                    continue
                model.all_objects.filter(tenant=sandbox).delete()
        sandbox.delete()

    return len(expired)
