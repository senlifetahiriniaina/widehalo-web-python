"""Test parametrique d'aller-retour export/import par entite (T3 du plan de
durcissement, CDC §8 couche 6 "Import/export round-trip").

Complete `test_tenant_portability.py` (qui ne verifie que `Document`) : on
enumere TOUTE sous-classe concrete de `BaseModel` presente dans l'application
(meme filtre que `tenant_export.export_tenant_archive` et
`sandbox.clone_tenant_to_sandbox` : on exclut les modeles abstraits et ceux
definis dans un module `*.tests.*`), on cree une instance representative via
la factory `factory_boy` correspondante (T1), on exporte le tenant source,
on reimporte dans un tenant cible frais, puis on verifie que l'enregistrement
importe correspond a l'original.

Semantique de comparaison des champs (cf. docstring de
`apps.core.services.tenant_export.import_tenant_archive`) :

- `id` change TOUJOURS a l'import (nouvel UUID genere) — jamais compare.
- `created_at`/`updated_at` sont regeneres par `auto_now_add`/`auto_now` au
  moment de la reecriture des lignes — jamais compares.
- `tenant`/`tenant_id` doit pointer vers le tenant CIBLE, pas la source.
- Les references generiques internes a l'archive (`content_type`+
  `object_id`, GenericForeignKey) sont remappees par `import_tenant_archive`
  — verifiees en comparant le nouvel `object_id` via le registre de
  remappage plutot que par egalite brute.
- Les UUID opaques inter-app (ex. `CrmLead.partner_id`, `AccPayment.partner_id`)
  ne sont PAS des ForeignKey Django (regle de couplage n°1 du CDC : jamais de
  FK Django entre apps metier) : ils doivent traverser l'export/import
  OCTET POUR OCTET, sans aucun remappage — verifies par egalite brute.
- Les ForeignKey Django "classiques" vers un AUTRE modele de la meme app
  (ex. `AccMoveLine.move` -> `AccMove`, tous deux exportes dans la meme
  archive) devraient, pour un round-trip correct, etre reecrites vers le NOUVEL
  id de l'objet parent reimporte (comme le sont deja les GenericForeignKey) :
  on verifie (a) que l'id a bien change par rapport a l'original et (b) que la
  ligne referencee est bien accessible dans le tenant CIBLE (pas de reference
  fantome vers une ligne du tenant source, invisible sous RLS)."""

from __future__ import annotations

import datetime
import importlib
import uuid
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Field, ForeignKey, Model

from apps.core.models.base import BaseModel
from apps.core.models.tenant import Tenant
from apps.core.services.tenant_export import export_tenant_archive, import_tenant_archive
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

# Champs jamais compares : regeneres/reattribues par construction a l'import.
_ALWAYS_SKIPPED_FIELDS = {"id", "tenant", "created_at", "updated_at"}

# `created_by`/`updated_by` pointent vers `core.User`, qui n'est PAS une
# sous-classe de `BaseModel` (pas de tenant, jamais inclus dans l'archive) —
# hors-sujet pour un round-trip de donnees tenant, et systematiquement None
# dans les factories T1 (jamais positionnes explicitement).
_NON_TENANT_FK_FIELDS = {"created_by", "updated_by", "actor"}

_FACTORY_MODULES = [
    "apps.core.tests.factories",
    "apps.partners.tests.factories",
    "apps.catalog.tests.factories",
    "apps.chat.tests.factories",
    "apps.accounting.tests.factories",
    "apps.crm.tests.factories",
    "apps.mrp.tests.factories",
    "apps.patronage.tests.factories",
]


def _all_base_model_subclasses() -> list[type[Model]]:
    """Meme filtre que `tenant_export.export_tenant_archive` /
    `sandbox.clone_tenant_to_sandbox` : toute sous-classe concrete de
    `BaseModel`, hors modeles abstraits et modeles de test."""
    models: list[type[Model]] = []
    for model in django_apps.get_models():
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            continue
        if model._meta.abstract or ".tests." in model.__module__:
            continue
        models.append(model)
    return models


def _build_factory_map() -> dict[type[Model], type[Any]]:
    """Associe chaque modele concret a sa factory `<ModelName>Factory`, en
    important les 8 modules `factories.py` de T1 et en faisant correspondre
    `factory._meta.model` au modele. Approche dynamique choisie plutot qu'un
    dict ecrit a la main : ~90 factories a repertorier, et la correspondance
    `factory._meta.model` est deja la source de verite portee par chaque
    factory elle-meme (pas de risque de desynchronisation si une factory est
    renommee)."""
    mapping: dict[type[Model], type[Any]] = {}
    for module_name in _FACTORY_MODULES:
        module = importlib.import_module(module_name)
        for name in dir(module):
            if not name.endswith("Factory"):
                continue
            candidate = getattr(module, name)
            meta = getattr(candidate, "_meta", None)
            model = getattr(meta, "model", None) if meta is not None else None
            if model is not None:
                mapping[model] = candidate
    return mapping


_MODELS = _all_base_model_subclasses()
_FACTORY_MAP = _build_factory_map()
_MISSING_FACTORIES = [m for m in _MODELS if m not in _FACTORY_MAP]
assert not _MISSING_FACTORIES, (
    "Modeles BaseModel sans factory correspondante (T1 incomplet) : "
    f"{[m.__name__ for m in _MISSING_FACTORIES]}"
)

# Limitation de conception connue, distincte du bug de remappage de FK
# corrige par cette tache : `SavedTableView.Meta.constraints` declare
# `uniq_saved_view` sur (owner, table_key, name) SANS inclure `tenant`.
# `owner` pointe vers `core.User`, qui n'est pas scope par tenant et n'est
# donc jamais reecrit a l'import — deux tenants distincts partageant le meme
# utilisateur et le meme nom de vue sauvegardee entrent alors en collision
# des que les deux lignes coexistent dans la meme base (exactement le
# scenario que ce test reproduit : tenant source + tenant cible reimporte
# cote a cote). Corriger cela demanderait d'ajouter `tenant` a la contrainte
# (migration de schema), hors perimetre de T3 (tache de tests uniquement) —
# consigne ici plutot que masque.
_KNOWN_LIMITATIONS = {
    "core.SavedTableView": (
        "uniq_saved_view (owner, table_key, name) n'inclut pas tenant — "
        "collision attendue quand tenant source et tenant cible coexistent "
        "avec le meme owner (cf. commentaire ci-dessus)."
    ),
}

_CASES = [
    pytest.param(
        model,
        _FACTORY_MAP[model],
        id=(case_id := f"{model._meta.app_label}.{model.__name__}"),
        marks=(
            [pytest.mark.xfail(reason=_KNOWN_LIMITATIONS[case_id], strict=True)]
            if case_id in _KNOWN_LIMITATIONS
            else []
        ),
    )
    for model in sorted(_MODELS, key=lambda m: (m._meta.app_label, m.__name__))
]


def _is_generic_fk_pair_field(field: Field) -> bool:
    return field.name in ("content_type", "object_id")


def _normalize(value: Any) -> Any:
    """Normalise pour comparaison : Decimal/UUID/date compares par egalite
    native. Les `datetime` sont tronquees a la milliseconde : le
    serialiseur "json" de Django (utilise par l'export/import) perd la
    precision sous la milliseconde a l'aller-retour — limite connue et
    sans impact metier (aucune regle de gestion ne depend d'un ecart
    inferieur a la milliseconde), pas une regression a corriger ici."""
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    return value


def _assert_field_matches(
    *,
    model: type[Model],
    field: Field,
    original: Model,
    imported: Model,
    target_tenant: Tenant,
) -> None:
    name = field.name

    if name in _ALWAYS_SKIPPED_FIELDS:
        return

    if name in _NON_TENANT_FK_FIELDS:
        # Hors du graphe tenant (User global) : doit rester identique
        # (jamais remappe, jamais recree).
        original_value = getattr(original, f"{name}_id")
        imported_value = getattr(imported, f"{name}_id")
        assert imported_value == original_value, (
            f"{model.__name__}.{name} (hors graphe tenant) a change alors qu'il "
            f"ne devrait jamais etre remappe : {original_value!r} -> {imported_value!r}"
        )
        return

    if isinstance(field, ForeignKey):
        if field.related_model is ContentType:
            # Le catalogue ContentType est global (pas dans l'archive) : id
            # inchangeable.
            assert imported.content_type_id == original.content_type_id
            return

        related_model = field.related_model
        original_value = getattr(original, field.attname)
        imported_value = getattr(imported, field.attname)

        if related_model not in _MODELS:
            # Cible hors du graphe BaseModel exporte (ex. `core.User`) :
            # jamais remappee, doit rester identique.
            assert imported_value == original_value, (
                f"{model.__name__}.{name} pointe hors du graphe tenant exporte "
                f"et ne devrait pas changer : {original_value!r} -> {imported_value!r}"
            )
            return

        # FK Django "classique" vers un AUTRE modele BaseModel exporte dans
        # la meme archive (ex. AccMoveLine.move -> AccMove) : un round-trip
        # correct doit la relier au nouvel id de l'objet parent reimporte.
        if original_value is None:
            assert imported_value is None, (
                f"{model.__name__}.{name} etait NULL sur l'original mais "
                f"vaut {imported_value!r} apres import"
            )
            return

        assert imported_value != original_value, (
            f"{model.__name__}.{name} pointe encore vers l'id D'ORIGINE "
            f"({original_value!r}) apres import — devrait avoir ete relie au "
            f"nouvel id du parent reimporte (comme le sont deja les "
            f"GenericForeignKey content_type/object_id dans "
            f"import_tenant_archive). Reference fantome vers une ligne du "
            f"tenant SOURCE, invisible sous RLS pour le tenant cible."
        )
        assert related_model.objects.filter(pk=imported_value).exists(), (
            f"{model.__name__}.{name} = {imported_value!r} n'est visible dans "
            f"aucune ligne du tenant cible {target_tenant.id} : reference "
            f"fantome apres import."
        )
        return

    if _is_generic_fk_pair_field(field) and name == "object_id":
        # object_id est une reference generique opaque (cible potentiellement
        # hors archive, cf. factories T1 qui pointent souvent vers un objet
        # non exporte) : import_tenant_archive ne la remappe QUE si une
        # entree correspondante existe dans le registre de remappage interne
        # a l'archive ; sinon elle reste inchangee. Pour une instance
        # representative isolee (pas de graphe de reference generique
        # construit dans le test), la valeur doit donc rester identique.
        assert getattr(imported, name) == getattr(original, name)
        return

    # Champ scalaire "normal" (CharField, DecimalField, JSONField, dates,
    # booleens, UUIDField opaque inter-app type `partner_id`...) : doit
    # traverser l'export/import a l'identique.
    original_value = _normalize(getattr(original, name))
    imported_value = _normalize(getattr(imported, name))
    assert imported_value == original_value, (
        f"{model.__name__}.{name} : {original_value!r} -> {imported_value!r}"
    )


@pytest.mark.parametrize(("model", "factory_cls"), _CASES)
def test_entity_round_trips_through_export_import(
    model: type[Model], factory_cls: type[Any]
) -> None:
    source = Tenant.objects.create(code=f"PE-SRC-{uuid.uuid4().hex[:8]}", name="Per-entity source")
    target = Tenant.objects.create(code=f"PE-DST-{uuid.uuid4().hex[:8]}", name="Per-entity target")

    with use_tenant(source.id):
        original = factory_cls(tenant=source)
        original.refresh_from_db()

    archive_bytes = export_tenant_archive(source)
    import_tenant_archive(archive_bytes, target_tenant=target)

    with use_tenant(target.id):
        imported = model.objects.get()
        assert imported.tenant_id == target.id

        for field in model._meta.get_fields():
            if not getattr(field, "concrete", False) or field.many_to_many:
                continue
            _assert_field_matches(
                model=model,
                field=field,
                original=original,
                imported=imported,
                target_tenant=target,
            )
