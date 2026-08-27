"""Export/import global d'un tenant en archive JSON+fichiers, pour la
portabilite des donnees (objectif : reimport verifie en moins de 30
minutes, teste en nightly — cf. plan). Le manifeste est VERSIONNE
(`FORMAT_VERSION`) : un export produit par une version anterieure de
l'application reste important dans une version plus recente grace au
registre de migrations `MANIFEST_MIGRATIONS` — l'inverse (importer un
export recent dans une version plus ancienne du code) n'est PAS garanti,
ce n'est pas l'usage vise (on restaure vers l'avant, jamais en arriere)."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from typing import Any

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.db.uuid7 import uuid7
from apps.core.models.base import BaseModel
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

FORMAT_VERSION = 1

# Registre de migrations de manifeste : {version_source: fonction_de_montee_de_version}.
# Exemple futur : MANIFEST_MIGRATIONS[1] = _migrate_v1_to_v2 (renommage de
# champ, restructuration...) — vide pour l'instant, FORMAT_VERSION=1 est la
# toute premiere version du format.
MANIFEST_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _upgrade_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    version = manifest["format_version"]
    if version > FORMAT_VERSION:
        raise ValueError(
            f"Format d'export v{version} inconnu — plus recent que la version "
            f"supportee par cette application (v{FORMAT_VERSION}). Aucune migration "
            f"disponible pour redescendre vers un format anterieur."
        )
    while version < FORMAT_VERSION:
        migration = MANIFEST_MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"Aucune migration disponible pour passer le format v{version} à "
                f"v{FORMAT_VERSION} — export trop ancien ou corrompu."
            )
        manifest = migration(manifest)
        version = manifest["format_version"]
    return manifest


def export_tenant_archive(tenant: Tenant) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        exported_labels: list[str] = []

        with activate_tenant(tenant.id):
            for model in django_apps.get_models():
                if not (isinstance(model, type) and issubclass(model, BaseModel)):
                    continue
                if model._meta.abstract or ".tests." in model.__module__:
                    continue

                queryset = model.all_objects.filter(tenant=tenant)
                if not queryset.exists():
                    continue

                content_type = ContentType.objects.get_for_model(model)
                label = f"{content_type.app_label}.{content_type.model}"
                data = serializers.serialize("json", queryset)
                archive.writestr(f"data/{label}.json", data)
                exported_labels.append(label)

        manifest: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "exported_at": timezone.now().isoformat(),
            "tenant_code": tenant.code,
            "models": exported_labels,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    return buffer.getvalue()


def import_tenant_archive(archive_bytes: bytes, *, target_tenant: Tenant) -> dict[str, int]:
    """Reimporte une archive de tenant. Les identifiants (UUID) sont
    globalement uniques en base (pas seulement par tenant) : on ne peut donc
    pas reinjecter tel quel un objet dont l'id d'origine existe deja (ex.
    reimport vers un tenant different alors que le tenant source est encore
    present dans la meme base). On genere donc de nouveaux id pour chaque
    objet importe, et on reporte ce remappage a la fois sur les references
    generiques internes a l'archive (`content_type`/`object_id`) ET sur les
    ForeignKey ordinaires vers d'autres `BaseModel` exportes ensemble — sans
    quoi un `AccMoveLine.move_id`, par exemple, continuerait de pointer vers
    la ligne du tenant SOURCE (id jamais reutilise, ligne source jamais
    supprimee), ce qui est a la fois incorrect et une fuite inter-tenant
    (la RLS du tenant cible ne verrait meme pas cette ligne). Les objets sont
    sauvegardes en plusieurs passes (une par "vague" de dependances FK
    resolues) car l'ordre d'export ne garantit aucun ordre topologique."""
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    manifest = json.loads(archive.read("manifest.json"))
    manifest = _upgrade_manifest(manifest)

    all_objects: dict[str, list[Any]] = {}
    id_remap: dict[tuple[str, str], Any] = {}
    for label in manifest["models"]:
        raw = archive.read(f"data/{label}.json").decode("utf-8")
        objects = list(serializers.deserialize("json", raw))
        for deserialized_obj in objects:
            instance: Any = deserialized_obj.object
            old_id = instance.pk
            new_id = uuid7()
            id_remap[(label, str(old_id))] = new_id
            instance.pk = new_id
            instance.id = new_id
            instance.tenant_id = target_tenant.id
        all_objects[label] = objects

    counts: dict[str, int] = {label: len(objects) for label, objects in all_objects.items()}
    content_type_labels: dict[int, str] = {}

    def _remap_generic_fk(imported: Any) -> None:
        content_type_id = getattr(imported, "content_type_id", None)
        object_id = getattr(imported, "object_id", None)
        if not (content_type_id and object_id):
            return
        referenced_label = content_type_labels.get(content_type_id)
        if referenced_label is None:
            content_type = ContentType.objects.filter(pk=content_type_id).first()
            if content_type is not None:
                referenced_label = f"{content_type.app_label}.{content_type.model}"
                content_type_labels[content_type_id] = referenced_label
        if referenced_label is not None:
            remapped = id_remap.get((referenced_label, str(object_id)))
            if remapped is not None:
                imported.object_id = str(remapped)

    def _remap_ordinary_fks(imported: Any) -> None:
        for field in type(imported)._meta.get_fields():
            is_to_one = getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)
            if not (is_to_one and getattr(field, "concrete", False)):
                continue
            related_model = field.related_model
            if not (isinstance(related_model, type) and issubclass(related_model, BaseModel)):
                continue
            old_fk_id = getattr(imported, field.attname)
            if old_fk_id is None:
                continue
            remapped = id_remap.get((related_model._meta.label_lower, str(old_fk_id)))
            if remapped is not None:
                setattr(imported, field.attname, remapped)
            # Sinon : la cible n'est pas dans cette archive (autre tenant
            # deja present en base, ex. FK vers `core.User` non tenant-scope)
            # — laissee inchangee.

    with activate_tenant(target_tenant.id):
        pending = [
            deserialized_obj for objects in all_objects.values() for deserialized_obj in objects
        ]
        while pending:
            still_pending = []
            for deserialized_obj in pending:
                imported = deserialized_obj.object
                _remap_generic_fk(imported)
                _remap_ordinary_fks(imported)
                try:
                    with transaction.atomic():
                        deserialized_obj.save()
                except IntegrityError:
                    still_pending.append(deserialized_obj)

            if len(still_pending) == len(pending):
                raise ValueError(
                    _(
                        "Impossible d'importer l'archive : dependances entre objets "
                        "non resolvables (reference manquante ou cycle)."
                    )
                )
            pending = still_pending

    return counts
