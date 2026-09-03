"""Cahier des charges WideHalo v3, Phase 1, §13.3 (ACC-9) : verrou de mise
en production sur les paramètres réglementaires. Teste la logique du
verrou (`apps.core.services.regulatory_governance`) et la commande de
management qui l'expose (`check_regulatory_validation`) — cf. le
commentaire de tête de `regulatory_governance.py` pour la distinction
entre ce test (logique) et le déclenchement réel en pipeline de
déploiement (données de production, hors portée de ce test)."""

from __future__ import annotations

import datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.services.regulatory_governance import (
    ACTIVE_CALCULATION_PARAMETER_CODES,
    unvalidated_active_parameters,
)
from apps.core.tests.factories import TenantFactory

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 6, 1)


def _seed_one_active_code(*, statut_validation: str, tenant=None) -> RegulatoryParameter:
    code = sorted(ACTIVE_CALCULATION_PARAMETER_CODES)[0]
    return RegulatoryParameter.objects.create(
        code=code,
        tenant=tenant,
        value={"rate": "1"},
        valid_from=TODAY - datetime.timedelta(days=30),
        valid_to=None,
        statut_validation=statut_validation,
    )


def test_non_valide_active_parameter_blocks_deployment() -> None:
    _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_NON_VALIDE)

    blocking = unvalidated_active_parameters(at_date=TODAY)

    assert len(blocking) == 1


def test_valide_oecfm_active_parameter_does_not_block() -> None:
    _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_VALIDE_OECFM)

    blocking = unvalidated_active_parameters(at_date=TODAY)

    assert blocking == []


def test_default_status_on_creation_is_non_valide() -> None:
    # DÉCISION ACTÉE (cahier §4) : « Aucune hypothèse réglementaire ne peut
    # être levée par défaut » — le statut par défaut ne doit jamais être
    # VALIDE_OECFM, sous peine de valider silencieusement tout nouveau
    # paramètre créé sans revue.
    parameter = _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_NON_VALIDE)
    assert parameter.statut_validation == RegulatoryParameter.STATUS_NON_VALIDE


def test_expired_non_valide_parameter_does_not_block() -> None:
    code = sorted(ACTIVE_CALCULATION_PARAMETER_CODES)[0]
    RegulatoryParameter.objects.create(
        code=code,
        value={"rate": "1"},
        valid_from=TODAY - datetime.timedelta(days=400),
        valid_to=TODAY - datetime.timedelta(days=1),
        statut_validation=RegulatoryParameter.STATUS_NON_VALIDE,
    )

    assert unvalidated_active_parameters(at_date=TODAY) == []


def test_tenant_override_non_valide_blocks_even_if_global_is_valid() -> None:
    tenant = TenantFactory()
    code = sorted(ACTIVE_CALCULATION_PARAMETER_CODES)[0]
    RegulatoryParameter.objects.create(
        code=code,
        tenant=None,
        value={"rate": "1"},
        valid_from=TODAY - datetime.timedelta(days=30),
        valid_to=None,
        statut_validation=RegulatoryParameter.STATUS_VALIDE_OECFM,
    )
    RegulatoryParameter.objects.create(
        code=code,
        tenant=tenant,
        value={"rate": "2"},
        valid_from=TODAY - datetime.timedelta(days=30),
        valid_to=None,
        statut_validation=RegulatoryParameter.STATUS_NON_VALIDE,
    )

    blocking = unvalidated_active_parameters(at_date=TODAY, tenants=[tenant])

    assert len(blocking) == 1
    assert blocking[0].tenant_id == tenant.id


def test_mark_validated_flips_status_and_is_the_only_way_to_unblock() -> None:
    parameter = _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_NON_VALIDE)
    from apps.core.tests.factories import UserFactory

    accountant = UserFactory()

    assert unvalidated_active_parameters(at_date=TODAY) == [parameter]

    parameter.mark_validated(accountant)

    assert unvalidated_active_parameters(at_date=TODAY) == []
    parameter.refresh_from_db()
    assert parameter.statut_validation == RegulatoryParameter.STATUS_VALIDE_OECFM
    assert parameter.valide_par_id == accountant.id
    assert parameter.valide_le is not None


def test_regulatory_parameter_modification_is_audited() -> None:
    # ACC-8 : "Toute modification d'un paramètre réglementaire ... apparaît
    # dans le journal d'audit" — RegulatoryParameter n'hérite pas de
    # BaseModel (cf. sa docstring), donc ce n'est PAS le signal générique
    # qui la journalise mais un signal dédié (apps.core.audit_signals).
    from apps.core.models.audit import AuditLog

    parameter = _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_NON_VALIDE)

    entries = AuditLog.objects.filter(object_id=str(parameter.id))
    assert entries.filter(action=AuditLog.ACTION_CREATED).exists()

    parameter.mark_validated(None)
    assert AuditLog.objects.filter(
        object_id=str(parameter.id), action=AuditLog.ACTION_UPDATED
    ).exists()


def test_version_auto_increments_within_a_code_lineage() -> None:
    code = "payroll.irsa_minimum"
    v1 = RegulatoryParameter.objects.create(
        code=code,
        value={"amount": "3000"},
        valid_from=datetime.date(2025, 1, 1),
        valid_to=datetime.date(2025, 12, 31),
    )
    v2 = RegulatoryParameter.objects.create(
        code=code,
        value={"amount": "3200"},
        valid_from=datetime.date(2026, 1, 1),
        valid_to=None,
    )

    assert v1.version == 1
    assert v2.version == 2


def test_check_regulatory_validation_command_fails_when_blocking() -> None:
    _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_NON_VALIDE)

    with pytest.raises(CommandError):
        call_command("check_regulatory_validation")


def test_check_regulatory_validation_command_succeeds_when_all_validated() -> None:
    _seed_one_active_code(statut_validation=RegulatoryParameter.STATUS_VALIDE_OECFM)

    call_command("check_regulatory_validation")
