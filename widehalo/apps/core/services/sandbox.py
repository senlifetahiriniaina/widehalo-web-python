"""Bac a sable par clonage : copie anonymisee d'un tenant pour tests/
formation, avec expiration automatique. Implementation simple, non
optimisee pour de gros volumes (cf. simplifications assumees du lot) —
suffisante tant que le volume de donnees reel n'existe pas encore.

**Correctif du chantier backup/restore** : `clone_tenant_to_sandbox`
recopiait les objets sans jamais reecrire leurs references (FK Django
classiques vers un autre `BaseModel` copie dans le meme lot, ni les
references generiques `content_type`/`object_id`) — exactement le bug deja
trouve et corrige dans `tenant_export.import_tenant_archive` par T3 (cf.
plan), jamais reporte ici a l'epoque. Desormais partage via
`apps.core.services.object_remap` (memes fonctions, memes garanties) —
plus une seule implementation divergente du meme algorithme."""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.db.uuid7 import uuid7
from apps.core.models.base import BaseModel
from apps.core.models.tenant import Tenant
from apps.core.services.object_remap import (
    IdRemap,
    regenerate_secret_token_fields,
    remap_all_references,
)
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

    # Premiere passe : attribue le nouvel id de chaque clone et construit
    # le registre de remappage AVANT de reecrire la moindre reference —
    # meme sequence que `tenant_export.import_tenant_archive` (on doit
    # connaitre TOUS les nouveaux id avant de pouvoir en referencer un
    # seul, l'ordre d'iteration ne garantissant aucun ordre topologique).
    id_remap: IdRemap = {}
    clones: list[Any] = []
    counter = 0
    for model, rows in rows_by_model.items():
        label = model._meta.label_lower
        for obj in rows:
            counter += 1
            clone = copy.copy(obj)
            new_id = uuid7()
            id_remap[(label, str(obj.pk))] = new_id
            clone.id = new_id
            clone.tenant = sandbox
            clone.tenant_id = sandbox.id
            clone._state.adding = True

            for field_name in PII_FIELD_NAMES:
                if hasattr(clone, field_name):
                    setattr(clone, field_name, _anonymize_field_value(field_name, counter))
            # Meme raisonnement que pour les PII ci-dessus, sur un registre
            # de champs distinct (cf. `object_remap.SECRET_TOKEN_FIELD_
            # NAMES`) : un jeton `unique=True` sans `tenant` dans sa
            # contrainte (ex. `PrjGuestAccess.token`) doit etre regenere,
            # jamais recopie tel quel, sous peine de collision UNIQUE avec
            # la ligne source ET de partage d'un meme credential entre le
            # tenant source et son bac a sable.
            regenerate_secret_token_fields(clone)

            clones.append(clone)

    content_type_labels: dict[int, str] = {}
    with activate_tenant(sandbox.id):
        pending = clones
        while pending:
            still_pending = []
            for clone in pending:
                remap_all_references(clone, id_remap, content_type_labels)
                try:
                    with transaction.atomic():
                        clone.save()
                except IntegrityError:
                    still_pending.append(clone)

            if len(still_pending) == len(pending):
                raise ValueError(
                    _(
                        "Impossible de cloner le tenant en bac a sable : dependances "
                        "entre objets non resolvables (reference manquante ou cycle)."
                    )
                )
            pending = still_pending

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
