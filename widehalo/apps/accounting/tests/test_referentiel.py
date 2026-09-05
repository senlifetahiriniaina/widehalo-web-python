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
from apps.accounting.services.chart_of_accounts import load_chart_of_accounts
from apps.accounting.services.default_accounts import (
    ROLE_FALLBACK_TYPE,
    resolve_default_account,
)
from apps.accounting.tests.factories import AccAccountFactory, AccFiscalYearFactory
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
        assert AccAccount.objects.filter(code="701").count() == 1
    with use_tenant(second.id):
        # Aucune levee : la contrainte porte sur le couple, pas sur le code.
        AccAccountFactory(tenant=second, code="701")
        assert AccAccount.objects.filter(code="701").count() == 1


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


def test_income_statement_structure_lives_in_the_framework() -> None:
    """D10-3 : la structure du compte de resultat est une donnee.

    Les 12 postes et les 9 soldes intermediaires I a IX etaient ecrits en
    Python (`_CR_NATURE_MAPPING` et la cascade de `income_statement`)."""
    framework = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)
    lines = framework.statement_structure["lines"]
    assert len([line for line in lines if line["kind"] == "poste"]) == 12
    romans = [line["roman"] for line in lines if line.get("roman")]
    assert romans == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    # Le chiffre d'affaires reste bien agrege depuis les comptes 70x.
    revenue = next(line for line in lines if line["key"] == "chiffre_affaires")
    assert revenue["natural"] == "credit"
    assert "701" in revenue["additive"]


def test_balance_sheet_presentation_order_lives_in_the_framework() -> None:
    """`_ASSET_TYPE_ORDER`/`_LIABILITY_TYPE_ORDER` etaient deux dictionnaires
    de module ; ils sont desormais portes par le referentiel."""
    framework = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)
    order = framework.statement_structure["balance_sheet_order"]
    assert order["asset"]["asset"] == 0
    assert order["liability"]["equity"] == 0


def test_a_second_framework_produces_its_own_statement_without_touching_python() -> None:
    """La preuve qui compte pour ACC-2 : changer de referentiel change l'etat
    financier, sans qu'une ligne de Python ne bouge.

    Le referentiel utilise ici est celui livre par la migration 0029 — un jeu
    de DEMONSTRATION, pas un plan SYSCOHADA reel, l'ADR le dit. Il suffit a
    prouver que la structure n'est plus dans le code."""
    from apps.accounting.services.reports import income_statement

    tenant = TenantFactory(country_code="CI")
    with use_tenant(tenant.id):
        load_chart_of_accounts(tenant)
        fiscal_year = AccFiscalYearFactory(tenant=tenant)
        rows = income_statement(fiscal_year)

    labels = [row["label"] for row in rows]
    assert "MARGE COMMERCIALE" in labels
    assert "RESULTAT NET" in labels
    # Aucun poste du PCG 2005 ne doit apparaitre : ce sont deux referentiels
    # distincts, jamais deux presentations du meme.
    assert "VALEUR AJOUTEE D'EXPLOITATION" not in labels
    assert [row["poste"] for row in rows if row["poste"]] == ["XA", "XI", "XV"]


def test_the_chart_loaded_depends_on_the_country_of_the_tenant() -> None:
    """ACC-1 et le defaut que D10-5 corrige.

    Les quatre chemins de creation de tenant appelaient
    `call_command("load_pcg2005")` INCONDITIONNELLEMENT : un tenant cree avec
    `--country=SN` recevait le plan comptable malgache, et le
    `chart_of_accounts_code` du profil pays n'etait lu par personne."""
    malagasy = TenantFactory(country_code="MG")
    ivorian = TenantFactory(country_code="CI")

    with use_tenant(malagasy.id):
        assert load_chart_of_accounts(malagasy) > 0
        codes = set(AccAccount.objects.values_list("code", flat=True))
    # "530" (Caisse) appartient au PCG 2005, "571" au jeu SYSCOHADA.
    assert "530" in codes and "571" not in codes

    with use_tenant(ivorian.id):
        assert load_chart_of_accounts(ivorian) > 0
        codes = set(AccAccount.objects.values_list("code", flat=True))
    assert "571" in codes and "530" not in codes


def test_a_country_without_referential_loads_nothing_rather_than_the_wrong_plan() -> None:
    """Un pays sans referentiel n'est pas une erreur de programmation, c'est
    une configuration a completer — et surtout, il ne doit pas recevoir le
    plan d'un autre pays."""
    tenant = TenantFactory(country_code="ZZ")
    with use_tenant(tenant.id):
        assert load_chart_of_accounts(tenant) == 0
        assert AccAccount.objects.count() == 0


def test_loaded_accounts_are_attached_to_their_chart() -> None:
    """La regle du cahier §12.2 de bout en bout : tenant -> pays -> framework
    -> plan -> comptes autorises."""
    tenant = TenantFactory(country_code="CI")
    with use_tenant(tenant.id):
        load_chart_of_accounts(tenant)
        charts = set(AccAccount.objects.values_list("chart__framework__code", flat=True))
    assert charts == {"SYSCOHADA_REVISE"}


def test_the_two_referentials_are_never_confused() -> None:
    """« Madagascar n'est pas membre de l'OHADA. […] Toute confusion entre les
    deux produit une comptabilite non conforme » (cahier §12.2). Les deux
    referentiels n'ont ni les memes classes, ni le meme compte de caisse."""
    pcg = AccFramework.objects.get(code=AccFramework.CODE_PCG2005)
    syscohada = AccFramework.objects.get(code=AccFramework.CODE_SYSCOHADA_REVISE)
    assert pcg.cash_account_prefix != syscohada.cash_account_prefix
    assert set(pcg.account_classes) != set(syscohada.account_classes)
    # Le jeu de demonstration doit se declarer comme tel, sans ambiguite.
    assert "DEMONSTRATION" in syscohada.validation_reserve
