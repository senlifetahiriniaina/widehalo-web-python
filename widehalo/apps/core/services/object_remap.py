"""Remappage d'identifiants partage entre `tenant_export.import_tenant_
archive` et `sandbox.clone_tenant_to_sandbox` : les deux operations
recopient un ensemble d'objets `BaseModel` d'un tenant source vers un
tenant cible avec de NOUVEAUX id (les id sont uniques globalement en
base, pas seulement par tenant — un objet ne peut jamais etre reinjecte
tel quel si son id d'origine existe deja ou si le tenant source coexiste
encore avec le tenant cible). Toute reference — FK Django "classique" vers
un autre `BaseModel` de la meme copie, ou reference generique
`content_type`/`object_id` — doit donc etre reecrite vers le NOUVEL id de
l'objet cible, sous peine de fuite/reference fantome inter-tenant (bug
reel trouve et corrige dans `import_tenant_archive` par T3, cf. plan —
`clone_tenant_to_sandbox` avait la MEME lacune, jamais corrigee a ce
moment-la, `id_remap`/`remap_generic_fk`/`remap_ordinary_fks` extraits ici
pour que les deux operations partagent desormais une seule implementation
au lieu de deux copies potentiellement divergentes."""

from __future__ import annotations

import secrets
from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.core.models.base import BaseModel

# `(label_modele, str(ancien_id)) -> nouvel_id` — `label_modele` est soit
# `app_label.model` (cote export/import, derive de `ContentType`), soit
# `model._meta.label_lower` (cote sandbox) — les deux formats coincident
# (`ContentType.model` est deja en minuscules), donc un seul dict sert aux
# deux appelants sans conversion.
IdRemap = dict[tuple[str, str], Any]

# Champs consideres comme des JETONS SECRETS uniques GLOBALEMENT (pas
# seulement par tenant, ex. `PrjGuestAccess.token`, `unique=True` SANS
# `tenant` dans la contrainte) — meme patron par NOM DE CHAMP que
# `sandbox.PII_FIELD_NAMES`. Recopier un tel objet sans regenerer ce champ
# echouerait sur la contrainte `UNIQUE` des que la source et la copie
# coexistent dans la meme base (import cote a cote d'un backup, clonage
# sandbox) — et, PIRE qu'une simple collision technique pour un champ qui
# sert de CREDENTIAL d'authentification anonyme, laisserait deux tenants
# distincts partager le MEME secret resolvable (fuite cross-tenant directe :
# le token du tenant source resoudrait alors, au choix du SGBD, vers l'une
# OU l'autre des deux lignes). Regenere via `secrets.token_urlsafe` — le
# meme generateur que celui utilise a la creation d'origine du jeton (cf.
# `apps.projects.services.guest_portal.create_guest_access`) ; convient a
# tout champ de ce registre car AUCUN n'a de contrainte de format au-dela de
# "chaine opaque unique" (contrairement a un champ structure : email,
# reference numerotee...).
SECRET_TOKEN_FIELD_NAMES = {"token"}


def regenerate_secret_token_fields(instance: Any) -> None:
    """Regenere en place tout champ de `SECRET_TOKEN_FIELD_NAMES` porte par
    `instance`, AVANT sauvegarde — a appeler par tout appelant qui recopie
    un `BaseModel` vers un nouveau tenant (`tenant_export.import_tenant_
    archive`, `sandbox.clone_tenant_to_sandbox`), au meme titre que le
    remappage d'id/references (cf. docstring de module)."""
    for field_name in SECRET_TOKEN_FIELD_NAMES:
        if hasattr(instance, field_name):
            setattr(instance, field_name, secrets.token_urlsafe(32))


def remap_generic_fk(imported: Any, id_remap: IdRemap, content_type_labels: dict[int, str]) -> None:
    """Reecrit `imported.object_id` (reference generique `content_type`/
    `object_id`) vers le nouvel id si sa cible fait partie du meme lot
    copie — sinon laissee inchangee (reference opaque hors de ce lot,
    jamais une erreur, cf. `tenant_export.py::import_tenant_archive`)."""
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


def remap_ordinary_fks(imported: Any, id_remap: IdRemap) -> None:
    """Reecrit toute ForeignKey/OneToOne Django "classique" vers un autre
    `BaseModel` copie dans le meme lot — vers son NOUVEL id. Une cible hors
    du lot (ex. `core.User`, jamais copie) reste inchangee, jamais une
    erreur."""
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
        # Sinon : la cible n'est pas dans ce lot (autre tenant deja present
        # en base) — laissee inchangee.


def remap_all_references(
    imported: Any, id_remap: IdRemap, content_type_labels: dict[int, str]
) -> None:
    """Convenance : applique les deux remappages ci-dessus en un appel —
    c'est l'ordre attendu par les deux appelants (generique puis FK
    classiques, meme sequence que l'implementation d'origine)."""
    remap_generic_fk(imported, id_remap, content_type_labels)
    remap_ordinary_fks(imported, id_remap)
