"""REP1 : registre central (`core.services.reports_registry`) — meme
discipline de test que `apps.core.tests.test_event_bus` pour le patron
`core.events`."""

from __future__ import annotations

import pytest

from apps.core.services.reports_registry import (
    get_registered_report,
    list_registered_reports,
    register_report,
)


def test_register_report_requires_at_least_one_renderer() -> None:
    with pytest.raises(ValueError, match="renderer"):
        register_report(
            owner_role="admin",
            description="Enregistrement de test, hors catalogue livré.",
            code="RPT-TEST-EMPTY",
            module="core",
            label="Vide",
            permission="core.view_tenant",
        )


def test_register_and_get_report_round_trips() -> None:
    def _rows(params: dict, actor) -> list[dict]:  # noqa: ANN001
        return [{"a": 1}]

    register_report(
        owner_role="admin",
        description="Enregistrement de test, hors catalogue livré.",
        code="RPT-TEST-ROWS",
        module="core",
        label="Test rows",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    report = get_registered_report("RPT-TEST-ROWS")
    assert report is not None
    assert report.supports_rows()
    assert not report.supports_pdf()
    assert report.render_rows is not None
    assert report.render_rows({}, None) == [{"a": 1}]


def test_9_business_modules_have_registered_at_least_one_report() -> None:
    """REP5 : chaque module qui avait deja des rapports construits
    (`accounting`/`crm`/`mrp`/`patronage`/`sales`/`purchase`/`stocks`/
    `logistics`/`payroll`) s'est bien auto-enregistre depuis son propre
    `apps.py::ready()` — deja execute par le simple fait que Django ait
    demarre pour cette suite de tests."""
    modules = {report.module for report in list_registered_reports()}
    expected = {
        "accounting",
        "crm",
        "mrp",
        "patronage",
        "sales",
        "purchase",
        "stocks",
        "logistics",
        "payroll",
    }
    missing = expected - modules
    assert not missing, f"modules sans aucun rapport enregistre : {missing}"


@pytest.mark.django_db
def test_the_persisted_mirror_carries_the_catalogue_metadata() -> None:
    """`RptDefinition` est le miroir PERSISTÉ du registre, par tenant.

    Trouvé en falsifiant : retirer la recopie du propriétaire et de la
    description dans `sync_report_definitions` ne faisait rougir aucun
    test. Le miroir aurait donc pu cesser silencieusement de porter le
    catalogue que le cahier demande, et l'écran l'affichant se serait vidé
    sans que rien ne proteste.

    Le catalogue est ce qui rend une rationalisation possible : « faut-il
    garder ce rapport ? » n'a pas de réponse si personne n'est désigné pour
    la donner."""
    from apps.core.models.tenant import Tenant
    from apps.core.services.reports_registry import get_registered_report
    from apps.core.tests.utils import use_tenant
    from apps.reporting.models import RptDefinition
    from apps.reporting.services.catalog import sync_report_definitions

    tenant = Tenant.objects.create(code="RPT-MIR", name="Miroir SARL")
    with use_tenant(tenant.id):
        sync_report_definitions(tenant)
        ligne = RptDefinition.objects.get(tenant=tenant, code="ACC-BAL")

    reference = get_registered_report("ACC-BAL")
    assert reference is not None
    assert ligne.owner_role == reference.owner_role != ""
    assert ligne.description == reference.description != ""


@pytest.mark.django_db
def test_the_mirror_is_refreshed_when_the_catalogue_changes() -> None:
    """Une resynchronisation doit propager une description corrigée. Sans
    cela, le miroir figerait le catalogue au premier déploiement et
    divergerait ensuite du registre — deux catalogues, dont un faux."""
    from apps.core.models.tenant import Tenant
    from apps.core.tests.utils import use_tenant
    from apps.reporting.models import RptDefinition
    from apps.reporting.services.catalog import sync_report_definitions

    tenant = Tenant.objects.create(code="RPT-MIR2", name="Miroir bis SARL")
    with use_tenant(tenant.id):
        sync_report_definitions(tenant)
        RptDefinition.objects.filter(tenant=tenant, code="ACC-BAL").update(
            description="périmée", owner_role="admin"
        )
        sync_report_definitions(tenant)
        ligne = RptDefinition.objects.get(tenant=tenant, code="ACC-BAL")

    assert ligne.description != "périmée"
    assert ligne.owner_role == "comptable"
