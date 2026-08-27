"""Couche 7 (T4/MIG du CDC) : reversibilite des migrations `core` qui
posent des garanties Postgres via `RunSQL` hors-modele — contrainte
d'exclusion (`btree_gist`) sur `RegulatoryParameter` et trigger
d'immuabilite sur `core_audit_log`.

Recreent tout le schema (django-test-migrations) : marquees `slow`."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import Error as DjangoDbError

pytestmark = pytest.mark.slow


@pytest.mark.django_db
def test_regulatory_parameter_no_overlap_constraint_applies_and_reverses(migrator) -> None:
    old_state = migrator.apply_initial_migration(
        ("core", "0008_countrydefaultsprofile_regulatoryparameter_auditlog_and_more")
    )
    param_model = old_state.apps.get_model("core", "RegulatoryParameter")

    param_model.objects.create(
        code="TVA", value={"rate": "20.00"}, valid_from=date(2026, 1, 1), valid_to=None
    )
    # Avant la migration : aucune contrainte, un chevauchement est accepte.
    param_model.objects.create(
        code="TVA", value={"rate": "21.00"}, valid_from=date(2026, 6, 1), valid_to=None
    )
    param_model.objects.all().delete()

    new_state = migrator.apply_tested_migration(("core", "0009_regulatory_parameter_no_overlap"))
    param_model = new_state.apps.get_model("core", "RegulatoryParameter")
    param_model.objects.create(
        code="TVA", value={"rate": "20.00"}, valid_from=date(2026, 1, 1), valid_to=None
    )
    with pytest.raises(DjangoDbError):
        param_model.objects.create(
            code="TVA", value={"rate": "21.00"}, valid_from=date(2026, 6, 1), valid_to=None
        )

    reverted_state = migrator.apply_tested_migration(
        ("core", "0008_countrydefaultsprofile_regulatoryparameter_auditlog_and_more")
    )
    param_model = reverted_state.apps.get_model("core", "RegulatoryParameter")
    # La contrainte a bien disparu : le meme chevauchement redevient possible.
    param_model.objects.create(
        code="TVA", value={"rate": "21.00"}, valid_from=date(2026, 6, 1), valid_to=None
    )
    # Nettoyage : le teardown du fixture `migrator` refait un `migrate`
    # jusqu'a la version la plus recente (qui recree la contrainte
    # d'exclusion) — des donnees se chevauchant encore la ferait echouer.
    param_model.objects.filter(code="TVA").delete()


@pytest.mark.django_db
def test_audit_log_immutable_trigger_applies_and_reverses(migrator) -> None:
    old_state = migrator.apply_initial_migration(("core", "0009_regulatory_parameter_no_overlap"))
    audit_model = old_state.apps.get_model("core", "AuditLog")

    entry = audit_model.objects.create(action="created", changes={"note": "avant migration"})
    entry.changes = {"note": "modifie avant migration : autorise"}
    entry.save(update_fields=["changes"])  # pas de trigger encore

    new_state = migrator.apply_tested_migration(("core", "0010_audit_log_immutable"))
    audit_model = new_state.apps.get_model("core", "AuditLog")
    entry = audit_model.objects.get(pk=entry.pk)
    entry.changes = {"note": "modifie apres migration : doit etre rejete"}
    with pytest.raises(DjangoDbError):
        entry.save(update_fields=["changes"])

    with pytest.raises(DjangoDbError):
        audit_model.objects.get(pk=entry.pk).delete()

    reverted_state = migrator.apply_tested_migration(
        ("core", "0009_regulatory_parameter_no_overlap")
    )
    audit_model = reverted_state.apps.get_model("core", "AuditLog")
    entry = audit_model.objects.get(pk=entry.pk)
    entry.changes = {"note": "modifie apres downgrade : de nouveau autorise"}
    entry.save(update_fields=["changes"])  # ne doit plus lever
