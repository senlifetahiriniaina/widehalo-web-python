"""X3 refonte UX (Sprint 8 / L5) : FMFP. Le detail de bulletin en
self-service (`payslip_detail`/`payslip_download`/`my_payslips`) a ete
retire par le cahier des charges Phase 3 (§6.1, decision D1 : "il n'existe
pas de portail salarie") -- voir `test_no_employee_self_service_portal`
ci-dessous, qui confirme l'absence de ces routes plutot que leur
comportement passe."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import NoReverseMatch, reverse

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.tests.factories import PrsEmployeeFactory

pytestmark = pytest.mark.django_db


def _new_payslip(tenant: Tenant, contract, period) -> PayPayslip:
    return PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )


def test_fmfp_pat_is_1_percent_of_base_cotisable_and_included_in_social_employer() -> None:
    tenant = Tenant.objects.create(code="PAY-FMFP", name="FMFP Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)

        fmfp_line = payslip.lines.get(code="FMFP_PAT")
        assert fmfp_line.amount == Decimal("12000")  # 1 200 000 * 1%
        assert fmfp_line.is_employer_charge is True
        # CNAPS_PAT (13%) + OSTIE_PAT (5%) + FMFP_PAT (1%) = 19% de 1 200 000
        assert payslip.social_employer == Decimal("228000")


def _employee_client(tenant: Tenant, employee_id) -> Client:
    user = User.objects.create_user(
        email=f"emp-{employee_id}@example.com", password="Str0ngPassw0rd!23"
    )
    PrsEmployeeFactory(tenant=tenant, id=employee_id, user=user)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_no_employee_self_service_portal_routes() -> None:
    """Cahier Phase 3 §6.1 (decision D1) : "le salarie n'a pas de compte...
    il n'existe pas de portail salarie" -- aucune route nommee
    `payroll:my_payslips`/`payroll:payslip_detail`/`payroll:payslip_download`
    ne doit plus exister, et l'URL historique `/payroll/<uuid>/` doit
    retourner 404 plutot que le detail d'un bulletin."""
    for route_name in ("my_payslips", "payslip_detail", "payslip_download"):
        with pytest.raises(NoReverseMatch):
            reverse(f"payroll:{route_name}", kwargs={"payslip_id": uuid.uuid4()})

    tenant = Tenant.objects.create(code="PAY-NOPORTAL", name="No Portal Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = _new_payslip(tenant, contract, period)
        compute_payslip(payslip)
        client = _employee_client(tenant, employee_id)

    assert client.get(f"/payroll/{payslip.id}/").status_code == 404
    assert client.get(f"/payroll/{payslip.id}/pdf/").status_code == 404


def test_payroll_root_renders_hr_dashboard_not_a_payslip_list() -> None:
    """La racine du module `payroll` n'est plus la liste des bulletins d'un
    employe : c'est desormais le tableau de bord RH, quel que soit
    l'utilisateur qui la consulte."""
    tenant = Tenant.objects.create(code="PAY-ROOT", name="Payroll Root Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        make_active_contract(tenant, employee_id=employee_id, wage_base=Decimal("1200000"))
        client = _employee_client(tenant, employee_id)

    response = client.get("/payroll/")
    assert response.status_code == 200
    assert "Tableau de bord Paie" in response.content.decode()
