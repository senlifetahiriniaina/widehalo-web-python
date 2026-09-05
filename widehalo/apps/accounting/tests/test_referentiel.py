"""D10 — referentiel comptable : le PCG 2005 est une donnee, pas une hypothese
de code (cahier Phase 1 §12.2, critere ACC-1).

Ce fichier verifie ce que le sprint D10-1 livre reellement, et rien de plus :
l'existence du referentiel amorce par la migration de donnees, le rattachement
des comptes au plan, et la contrainte d'unicite `(tenant, code)` qui n'existait
qu'en discipline applicative. La portabilite vers un second referentiel — la
preuve qui ferme ACC-2 — est l'objet du sprint D10-6, pas de celui-ci.
"""

from __future__ import annotations

import pytest
from django.db import transaction
from django.db.utils import IntegrityError

from apps.accounting.models import (
    AccAccount,
    AccAccountMapping,
    AccChartOfAccounts,
    AccFramework,
    AccTenantDefaultAccount,
)
from apps.accounting.services.default_accounts import (
    ROLE_FALLBACK_TYPE,
    resolve_default_account,
)
from apps.accounting.tests.factories import AccAccountFactory
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_pcg2005_framework_is_seeded_by_migration() -> None:
    """La migration `0026_seed_pcg2005_framework` amorce le referentiel."""
    framework = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)
    assert framework.default_country_code == "MG"
    assert framework.is_active


def test_framework_carries_what_used_to_be_hardcoded() -> None:
    """Les constantes PCG du code applicatif sont desormais des donnees.

    Chaque valeur est reprise a l'identique de sa constante d'origine — cette
    migration deplace, elle ne corrige pas."""
    framework = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)

    # `chart_of_accounts.SUSPENSE_ACCOUNT_CODE` et son `account_class=4`.
    assert framework.suspense_account_code == "471"
    assert framework.suspense_account_class == 4
    # Prefixes de `_DEFAULT_JOURNALS` (journaux BQ et CAI).
    assert framework.bank_account_prefix == "512"
    assert framework.cash_account_prefix == "530"
    # Classes de `reports.py` : compte de resultat par fonction, flux de
    # tresorerie.
    assert framework.expense_class == 6
    assert framework.income_class == 7
    assert framework.investing_class == 2
    # `ircm.py::_FINANCIAL_INCOME_PREFIXES`.
    assert framework.financial_income_prefixes == ["76", "77"]
    # `dcom.py::_CLASSIFICATION_BY_PCG_CLASS`.
    assert framework.class_classification["4"] == "tiers"
    # Le help_text "Classe PCG, 1 a 7" devient une donnee du referentiel.
    assert sorted(framework.account_classes) == ["1", "2", "3", "4", "5", "6", "7"]


def test_validation_reserve_is_data_not_a_docstring() -> None:
    """La reserve OECFM sort de la docstring de `chart_of_accounts.py`.

    Consequence n°5 de l'ADR : rendre le referentiel parametrable ne valide
    rien — la reserve doit rester visible, donc affichable."""
    framework = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)
    assert "OECFM" in framework.validation_reserve


def test_default_chart_for_madagascar_points_at_the_real_fixture() -> None:
    chart = AccChartOfAccounts.objects.get(framework__code="PCG2005", country_code="MG")
    assert chart.is_default_for_country
    assert chart.fixture_name == "pcg2005_mg.json"


def test_existing_accounts_are_attached_to_the_chart() -> None:
    """La migration de reprise ne laisse aucun compte orphelin."""
    tenant = TenantFactory()
    chart = AccChartOfAccounts.objects.get(framework__code="PCG2005", country_code="MG")
    with use_tenant(tenant.id):
        account = AccAccountFactory(tenant=tenant, chart=chart)
        assert account.chart_id == chart.id
        assert AccAccount.objects.filter(chart__isnull=True).count() == 0


def test_account_code_is_unique_per_tenant_at_the_database_level() -> None:
    """La contrainte est portee par la base, pas par la discipline applicative.

    Avant D10, rien n'empechait un import de creer deux comptes de meme code :
    la resolution des comptes par defaut faisait un `.first()` sans `order_by`,
    donc le resultat dependait de ce que Postgres decidait de rendre."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        AccAccountFactory(tenant=tenant, code="701")
        with pytest.raises(IntegrityError), transaction.atomic():
            AccAccountFactory(tenant=tenant, code="701")


def test_the_same_code_remains_possible_in_two_tenants() -> None:
    """L'unicite est par tenant, jamais globale — deux clients ont chacun
    leur compte 701."""
    first, second = TenantFactory(), TenantFactory()
    with use_tenant(first.id):
        AccAccountFactory(tenant=first, code="701")
    with use_tenant(second.id):
        AccAccountFactory(tenant=second, code="701")
    assert AccAccount.all_objects.filter(code="701").count() == 2


def test_default_account_role_is_unique_per_tenant() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        account = AccAccountFactory(tenant=tenant, code="701", type=AccAccount.TYPE_INCOME)
        AccTenantDefaultAccount.objects.create(
            tenant=tenant, role=AccTenantDefaultAccount.ROLE_SALE_INCOME, account=account
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            AccTenantDefaultAccount.objects.create(
                tenant=tenant, role=AccTenantDefaultAccount.ROLE_SALE_INCOME, account=account
            )


def test_account_mapping_is_delivered_empty() -> None:
    """Le cahier §12.2 la veut livree sans usage immediat : « son cout est
    faible maintenant et elle sera la piece centrale du deploiement OHADA »."""
    assert AccAccountMapping.objects.count() == 0


def test_configured_default_account_wins_over_the_type_fallback() -> None:
    """Le registre l'emporte : c'est tout l'objet de D10-2."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        fallback = AccAccountFactory(tenant=tenant, code="701", type=AccAccount.TYPE_INCOME)
        chosen = AccAccountFactory(tenant=tenant, code="707", type=AccAccount.TYPE_INCOME)
        assert resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_SALE_INCOME) == fallback
        AccTenantDefaultAccount.objects.create(
            tenant=tenant, role=AccTenantDefaultAccount.ROLE_SALE_INCOME, account=chosen
        )
        assert resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_SALE_INCOME) == chosen


def test_the_type_fallback_is_deterministic() -> None:
    """Le defaut corrige : `.first()` sans `order_by` renvoyait le compte que
    Postgres decidait de rendre. Le repli est desormais ordonne par code."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        AccAccountFactory(tenant=tenant, code="708", type=AccAccount.TYPE_INCOME)
        AccAccountFactory(tenant=tenant, code="701", type=AccAccount.TYPE_INCOME)
        AccAccountFactory(tenant=tenant, code="707", type=AccAccount.TYPE_INCOME)
        for _ in range(3):
            resolved = resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_SALE_INCOME)
            assert resolved is not None
            assert resolved.code == "701"


def test_resolution_returns_none_rather_than_raising() -> None:
    """Discipline de toute cette surface : un tenant mal configure n'est pas
    un bug du module appelant."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert resolve_default_account(tenant, AccTenantDefaultAccount.ROLE_SALE_INCOME) is None


def test_every_role_has_a_fallback_type() -> None:
    """Aucun role ne peut rester sans repli : un role ajoute sans entree dans
    ROLE_FALLBACK_TYPE resoudrait silencieusement `None`."""
    roles = {role for role, _ in AccTenantDefaultAccount.ROLE_CHOICES}
    assert roles == set(ROLE_FALLBACK_TYPE)
