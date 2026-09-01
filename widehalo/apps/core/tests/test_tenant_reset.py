"""Tests de `apps.core.services.tenant_reset.reset_tenant_data` (BKP1) :
round-trip reset+reseed identique a un tenant neuf, `User`/`Tenant`/
`UserTenantMembership` preserves, garde-fou « aucun progres »."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.accounting.models import AccAccount, AccJournal
from apps.core.models.risk import CATEGORY_OTHER, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.smart_defaults import apply_country_defaults
from apps.core.services.tenant_reset import reset_tenant_data
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLostReason, CrmPipeline
from apps.helpdesk.models import HlpTicketTypeCatalog

pytestmark = pytest.mark.django_db


def _create_tenant_like_command(code: str) -> Tenant:
    """Reproduit exactement la sequence de
    `apps.core.management.commands.create_tenant` (utilisee ici comme
    reference de comparaison, pas comme sujet du test)."""
    tenant = Tenant.objects.create(code=code, name=code, country_code="MG")
    apply_country_defaults(tenant, "MG")
    call_command("load_ticket_type_catalog", tenant=tenant.code)
    call_command("load_pcg2005", tenant=tenant.code)
    call_command("load_default_journals", tenant=tenant.code)
    call_command("load_default_pipeline", tenant=tenant.code)
    call_command("load_default_lost_reasons", tenant=tenant.code)
    return tenant


def test_reset_with_reseed_matches_a_freshly_created_tenant() -> None:
    reference = _create_tenant_like_command("RESET-REF")
    reference_accounts = AccAccount.all_objects.filter(tenant=reference).count()
    reference_journals = AccJournal.all_objects.filter(tenant=reference).count()
    reference_ticket_types = HlpTicketTypeCatalog.all_objects.filter(tenant=reference).count()
    reference_pipelines = CrmPipeline.all_objects.filter(tenant=reference).count()
    reference_lost_reasons = CrmLostReason.all_objects.filter(tenant=reference).count()
    assert reference_accounts > 0
    assert reference_journals > 0
    assert reference_ticket_types > 0
    assert reference_pipelines == 1
    assert reference_lost_reasons == 7

    subject = _create_tenant_like_command("RESET-SUBJ")
    owner = User.objects.create_user(email="owner@reset.test", password="Str0ngPassw0rd!23")
    with use_tenant(subject.id):
        RiskItem.objects.create(
            tenant=subject,
            category=CATEGORY_OTHER,
            likelihood=3,
            impact=3,
            score=9,
            owner=owner,
        )
    assert RiskItem.all_objects.filter(tenant=subject).count() == 1

    reset_tenant_data(subject, reseed=True)

    assert RiskItem.all_objects.filter(tenant=subject).count() == 0
    assert AccAccount.all_objects.filter(tenant=subject).count() == reference_accounts
    assert AccJournal.all_objects.filter(tenant=subject).count() == reference_journals
    assert HlpTicketTypeCatalog.all_objects.filter(tenant=subject).count() == reference_ticket_types
    assert CrmPipeline.all_objects.filter(tenant=subject).count() == reference_pipelines
    assert CrmLostReason.all_objects.filter(tenant=subject).count() == reference_lost_reasons


def test_reset_preserves_tenant_user_and_membership() -> None:
    tenant = _create_tenant_like_command("RESET-KEEP")
    user = User.objects.create_user(email="kept@reset.test", password="Str0ngPassw0rd!23")
    membership = UserTenantMembership.objects.create(user=user, tenant=tenant)

    reset_tenant_data(tenant, reseed=False)

    assert Tenant.objects.filter(id=tenant.id).exists()
    assert User.objects.filter(id=user.id).exists()
    assert UserTenantMembership.objects.filter(id=membership.id).exists()


def test_reset_without_reseed_skips_default_loading() -> None:
    tenant = _create_tenant_like_command("RESET-NORESEED")
    assert AccAccount.all_objects.filter(tenant=tenant).count() > 0

    reset_tenant_data(tenant, reseed=False)

    # Aucune reinjection du plan comptable/journaux/catalogue par defaut :
    # cas interne a `tenant_backup.restore_tenant_from_archive`, qui
    # reimporte de vraies donnees juste apres (cf. docstring du service).
    assert AccAccount.all_objects.filter(tenant=tenant).count() == 0
    assert AccJournal.all_objects.filter(tenant=tenant).count() == 0
    assert HlpTicketTypeCatalog.all_objects.filter(tenant=tenant).count() == 0


# Garde-fou « aucun progres » (mirroring `import_tenant_archive`) : aucun cas
# reel n'existe dans ce schema (les FK tenant-scopees s'effacent toutes en
# quelques passages, cf. tests ci-dessus qui passent sans jamais lever) —
# teste donc directement la logique de detection de progres plutot que de
# forcer un scenario artificiel qui ne refleterait pas ce schema reel.
def test_reset_raises_when_a_pass_makes_no_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db.models.deletion import ProtectedError

    from apps.core.services import tenant_reset as tenant_reset_module

    tenant = _create_tenant_like_command("RESET-STUCK")

    class _AlwaysProtectedQuerySet:
        def delete(self):
            raise ProtectedError("stuck", set())

    class _StuckModelManager:
        @staticmethod
        def filter(**kwargs):
            return _AlwaysProtectedQuerySet()

    class _StuckModel:
        _meta = type("Meta", (), {"label_lower": "stuck.model"})()
        all_objects = _StuckModelManager()

    monkeypatch.setattr(
        tenant_reset_module,
        "iter_concrete_basemodel_subclasses",
        lambda: iter([_StuckModel]),
    )

    with pytest.raises(ValueError):
        reset_tenant_data(tenant, reseed=False)
