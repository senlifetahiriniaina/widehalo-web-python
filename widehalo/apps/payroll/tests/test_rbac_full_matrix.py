"""Bloc E, E8 (PAY-11) : RBAC de `apps.payroll` testé sur l'ensemble des
13 rôles standard (`settings.CORE_STANDARD_ROLES`), pas sur un seul rôle
manager isolé comme le relevait l'audit Phase 3 (§5, PAY-11 🟡 :
« masquage/scope réels mais testés sur un seul rôle manager »). Couvre
aussi, en régression, les 2 fuites RBAC déjà identifiées ET corrigées
par ce même audit §5 (portail salarié self-service retiré par P1/D1 ;
export planifié recloisonné par P5) — ce fichier ne corrige rien, il
prouve que c'est resté corrigé.

Portée du test de matrice API (`test_api_permission_matrix_matches_
expected_role_actions`) : vérifie UNIQUEMENT la porte d'accès
(`@require_permission`, N2) — 403 pour tout rôle sans la permission
requise, PAS 403 pour le ou les rôles qui l'ont — jamais le succès
métier complet de chaque action (déjà couvert exhaustivement par les
tests dédiés de chaque sprint E1-E7). Cette distinction permet
d'utiliser des identifiants de chemin ALÉATOIRES/inexistants pour les
19 endpoints × 13 rôles sans construire un scénario métier complet pour
chaque combinaison : lecture directe de `apps/core/services/
permissions.py::_PermissionGuardedView.__call__` confirme que le
contrôle `user.has_perm(...)` s'exécute AVANT tout appel à la fonction
vue (donc avant tout `get_object_or_404`) — un rôle autorisé reçoit au
pire un 404/400 sur un identifiant fictif, jamais un 403.

`EXPECTED_PAYROLL_ACTIONS` est un PIN littéral de
`ROLE_APP_PERMISSIONS["payroll"]` au moment de ce sprint — jamais
réimporté depuis `apps.core.services.rbac_policy` : un test qui
comparerait ce module à lui-même ne détecterait jamais une régression
accidentelle de la matrice (un rôle qui gagnerait ou perdrait un accès
payroll par erreur ailleurs dans le code)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from django.core import mail
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django_otp.oath import totp
from ninja_jwt.tokens import RefreshToken

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.tests.factories import PrsEmployeeFactory
from apps.reporting.models import RptSchedule
from apps.reporting.services.scheduling import run_schedule

pytestmark = pytest.mark.django_db

_STAFF_ROLES = {"rh", "admin", "direction"}

# Pin explicite de ROLE_APP_PERMISSIONS["payroll"] (Bloc E, E8) — cf.
# docstring de module pour la justification de ne PAS réimporter le dict
# source.
EXPECTED_PAYROLL_ACTIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(),
    "direction": frozenset(),
    "comptable": frozenset(),
    "commercial": frozenset(),
    "resp_commercial": frozenset({"view"}),
    "acheteur": frozenset(),
    "resp_production": frozenset({"view"}),
    "chef_atelier": frozenset({"view"}),
    "magasinier": frozenset(),
    "rh": frozenset({"view", "add", "change"}),
    "collaborateur": frozenset(),
    "caissier": frozenset(),
    "controleur_gestion": frozenset(),
}

assert set(EXPECTED_PAYROLL_ACTIONS) == set(settings.CORE_STANDARD_ROLES), (
    "13 rôles attendus — la liste des rôles standard a changé, cf. settings.CORE_STANDARD_ROLES."
)


def _mint_token(user: User) -> str:
    return str(RefreshToken.for_user(user).access_token)


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def _web_client_for_role(tenant: Tenant, role: str) -> Client:
    """Client HTTP session Django pour `role` — deux flux d'authentification
    selon `settings.CORE_MFA_REQUIRED_ROLES` (l'API JWT n'est jamais
    concernée par la MFA, cf. `apps.core.middleware.
    MFAEnforcementMiddleware`, mais l'accès WEB par session l'est) :
    login réel + enrôlement/vérification TOTP pour un rôle MFA-requis
    (même patron que `apps.payroll.tests.factories.staff_client`,
    généralisé ici aux 13 rôles), `force_login` sinon (même patron que
    `apps.payroll.tests.factories.employee_client`)."""
    user = User.objects.create_user(
        email=f"{role}-web-e8@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, role)
    client = Client()
    if role in settings.CORE_MFA_REQUIRED_ROLES:
        response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
        assert response.status_code == 302, response.content
        device = mfa_service.enroll_device(user)
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        token = str(totp(device.bin_key)).zfill(6)
        verify_response = client.post("/mfa/", {"token": token})
        assert verify_response.status_code == 302, verify_response.content
    else:
        client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _api_endpoints() -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """(méthode, chemin, permission requise, corps JSON) pour les 19
    endpoints de `apps/payroll/api.py` — un seul UUID aléatoire partagé
    partout (jamais un objet réel : cf. docstring de module) ; les corps
    contiennent tous les champs obligatoires de leur `Schema` (sinon
    django-ninja renverrait 422 avant même d'atteindre `require_
    permission`, masquant la permission testée pour TOUS les rôles)."""
    rid = uuid.uuid4()
    return [
        ("get", "/api/v1/payroll/contracts", "payroll.view_paycontract", None),
        (
            "post",
            "/api/v1/payroll/contracts",
            "payroll.add_paycontract",
            {
                "employee_id": str(rid),
                "type_id": str(rid),
                "date_start": "2026-01-01",
                "wage_base": "100000",
                "salary_structure_id": str(rid),
            },
        ),
        (
            "post",
            f"/api/v1/payroll/contracts/{rid}/amend",
            "payroll.add_paycontract",
            {"date_start": "2026-01-01"},
        ),
        ("get", "/api/v1/payroll/structures", "payroll.view_paysalarystructure", None),
        ("get", "/api/v1/payroll/periods", "payroll.view_payperiod", None),
        (
            "post",
            "/api/v1/payroll/periods",
            "payroll.add_payperiod",
            {
                "code": f"E8-{rid.hex[:8]}",
                "date_from": "2099-01-01",
                "date_to": "2099-01-31",
                "payment_date": "2099-01-31",
            },
        ),
        (
            "post",
            f"/api/v1/payroll/periods/{rid}/compute",
            "payroll.change_payperiod",
            {"employee_ids": []},
        ),
        ("post", f"/api/v1/payroll/periods/{rid}/verify", "payroll.change_payperiod", {}),
        ("post", f"/api/v1/payroll/periods/{rid}/validate", "payroll.change_payperiod", {}),
        ("get", f"/api/v1/payroll/batches/{rid}/anomalies", "payroll.view_paybatch", None),
        (
            "post",
            f"/api/v1/payroll/batches/{rid}/anomalies/acknowledge",
            "payroll.change_paybatch",
            {"payslip_id": str(rid), "code": "x", "reason": "x"},
        ),
        ("post", f"/api/v1/payroll/periods/{rid}/pay", "payroll.change_payperiod", {}),
        ("post", f"/api/v1/payroll/periods/{rid}/close", "payroll.change_payperiod", {}),
        ("get", "/api/v1/payroll/payslips", "payroll.view_paypayslip", None),
        ("post", f"/api/v1/payroll/payslips/{rid}/recompute", "payroll.change_paypayslip", {}),
        ("get", f"/api/v1/payroll/payslips/{rid}/pdf", "payroll.view_paypayslip", None),
        ("get", "/api/v1/payroll/declarations", "payroll.view_paydeclaration", None),
        ("get", "/api/v1/payroll/advances", "payroll.view_payadvance", None),
        (
            "post",
            "/api/v1/payroll/advances",
            "payroll.add_payadvance",
            {"employee_id": str(rid), "date": "2026-01-01", "amount": "1000"},
        ),
    ]


def _required_action(permission: str) -> str:
    codename = permission.split(".", 1)[1]
    for action in ("view", "add", "change"):
        if codename.startswith(f"{action}_"):
            return action
    raise AssertionError(f"Codename de permission non reconnu : {permission}")


def test_api_permission_matrix_matches_expected_role_actions() -> None:
    tenant = Tenant.objects.create(code="PAY-E8-API", name="E8 API matrix")
    violations: list[str] = []

    for role, allowed_actions in EXPECTED_PAYROLL_ACTIONS.items():
        user = User.objects.create_user(email=f"{role}-api-e8@example.com", password="x")
        grant_role(user, role)
        headers = _headers(_mint_token(user), str(tenant.id))
        client = Client()

        for method, path, permission, body in _api_endpoints():
            should_pass = _required_action(permission) in allowed_actions
            response = (
                client.get(path, **headers)
                if method == "get"
                else client.post(path, body, content_type="application/json", **headers)
            )
            is_403 = response.status_code == 403
            if should_pass and is_403:
                violations.append(
                    f"{role} : {method.upper()} {path} attendu autorisé ({permission}), reçu 403."
                )
            elif not should_pass and not is_403:
                violations.append(
                    f"{role} : {method.upper()} {path} attendu refusé ({permission}), "
                    f"reçu {response.status_code} (pas 403)."
                )

    assert not violations, "\n".join(violations)


def test_html_screens_permission_matrix() -> None:
    """`hr_dashboard` (jamais 403, seul le masquage des montants varie) et
    `rubric_simulation`/`regularization_screen` (403 hors `_STAFF_ROLES`)
    — les 2 derniers écrans consommés respectivement par E4 et E7."""
    tenant = Tenant.objects.create(code="PAY-E8-HTML", name="E8 HTML matrix")
    violations: list[str] = []

    for role in EXPECTED_PAYROLL_ACTIONS:
        client = _web_client_for_role(tenant, role)

        dashboard_response = client.get("/payroll/")
        if dashboard_response.status_code != 200:
            violations.append(
                f"{role} : hr_dashboard attendu 200, reçu {dashboard_response.status_code}."
            )

        expected = 200 if role in _STAFF_ROLES else 403
        for path in ("/payroll/simulation/", "/payroll/regularisation/"):
            response = client.get(path)
            if response.status_code != expected:
                violations.append(
                    f"{role} : {path} attendu {expected}, reçu {response.status_code}."
                )

    assert not violations, "\n".join(violations)


def test_manager_roles_see_only_their_own_unmasked_payslip() -> None:
    """N3 (own) + N4 (masquage montants) exercés ensemble, sur les 3 rôles
    managers réellement dotés d'un accès `payroll` (`resp_commercial`/
    `resp_production`/`chef_atelier`, tous `{"view"}` seul) — l'audit
    Phase 3 §5 relevait que ces disciplines n'étaient testées que sur UN
    SEUL rôle manager ; ici les 3."""
    tenant = Tenant.objects.create(code="PAY-E8-N34", name="E8 N3/N4")
    role_tokens: dict[str, tuple[str, uuid.UUID]] = {}
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        other_contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        other_payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=other_contract.employee_id,
            contract=other_contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(other_payslip)

        for role in ("resp_commercial", "resp_production", "chef_atelier"):
            user = User.objects.create_user(email=f"{role}-n34-e8@example.com", password="x")
            grant_role(user, role)
            own_contract = make_active_contract(
                tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
            )
            PrsEmployeeFactory(tenant=tenant, id=own_contract.employee_id, user=user)
            own_payslip = PayPayslip.objects.create(
                tenant=tenant,
                employee_id=own_contract.employee_id,
                contract=own_contract,
                period=period,
                date_from=period.date_from,
                date_to=period.date_to,
            )
            compute_payslip(own_payslip)
            role_tokens[role] = (_mint_token(user), own_contract.employee_id)

    for role, (token, own_employee_id) in role_tokens.items():
        response = Client().get("/api/v1/payroll/payslips", **_headers(token, str(tenant.id)))
        assert response.status_code == 200, (role, response.content)
        body = response.json()
        employee_ids = {entry["employee_id"] for entry in body}
        assert employee_ids == {str(own_employee_id)}, (role, employee_ids)
        for entry in body:
            assert "gross" not in entry
            assert "net_to_pay" not in entry


def test_no_self_service_portal_route_for_any_role() -> None:
    """Régression, fuite #1 de l'audit Phase 3 §5 (décision D1/P1) :
    aucune route `my_payslips`/`payslip_detail`/`payslip_download`
    n'existe plus (indépendant du rôle, la route elle-même a été
    retirée) et l'URL historique `/payroll/<uuid>/` renvoie 404 pour
    N'IMPORTE QUEL rôle, y compris `rh` (qui a pourtant add/change/view
    sur `PayPayslip`) — la preuve que c'est une route réellement
    retirée, pas seulement un gap RBAC qu'un rôle bien placé
    contournerait."""
    for route_name in ("my_payslips", "payslip_detail", "payslip_download"):
        with pytest.raises(NoReverseMatch):
            reverse(f"payroll:{route_name}", kwargs={"payslip_id": uuid.uuid4()})

    tenant = Tenant.objects.create(code="PAY-E8-PORTAL", name="E8 portal regression")
    for role in EXPECTED_PAYROLL_ACTIONS:
        client = _web_client_for_role(tenant, role)
        response = client.get(f"/payroll/{uuid.uuid4()}/")
        assert response.status_code == 404, (role, response.status_code)


def test_scheduled_payslip_report_excludes_recipients_without_payroll_access() -> None:
    """Régression, fuite #2 de l'audit Phase 3 §5 (décision P5) : « un
    `rh` pouvait planifier PAY-BULL... vers des destinataires n'ayant
    eux-mêmes pas accès à la paie » — `apps.reporting.services.
    scheduling.run_schedule` revalide désormais CHAQUE destinataire à
    chaque exécution (déjà testé génériquement dans `apps.reporting.
    tests.test_scheduling`) ; ce test-ci rejoue le scénario EXACT
    décrit par l'audit avec le VRAI rapport paie (`PAY-BULL`, cf.
    `apps.payroll.services.reports_registration`) plutôt qu'un rapport
    de test générique."""
    tenant = Tenant.objects.create(code="PAY-E8-RPT", name="E8 scheduled export")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=contract.employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)

        creator = User.objects.create_user(email="rh-e8-rpt@example.com", password="x")
        grant_role(creator, "rh")
        authorized_recipient = User.objects.create_user(
            email="rh-e8-rpt-to@example.com", password="x"
        )
        grant_role(authorized_recipient, "rh")
        unauthorized_recipient = User.objects.create_user(
            email="commercial-e8-rpt@example.com", password="x"
        )
        grant_role(unauthorized_recipient, "commercial")

        schedule = RptSchedule.objects.create(
            tenant=tenant,
            name="Bulletin planifié",
            report_code="PAY-BULL",
            format="pdf",
            frequency=RptSchedule.FREQUENCY_MONTHLY,
            next_run_at=timezone.now(),
            params={"object_id": str(payslip.id)},
            created_by=creator,
        )
        schedule.recipients.add(authorized_recipient, unauthorized_recipient)

        run_schedule(schedule)
        schedule.refresh_from_db()

        assert schedule.enabled is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [authorized_recipient.email]
