"""INT4 (chantier interactivite native inter-modules — « faire le max avec
AutoFlow ») : verifie que `seed_default_flows` construit reellement un
`AutoFlow` ACTIF fonctionnel — pas seulement des enregistrements en base,
mais un flux qui declenche VRAIMENT un `AutoRun` "success"/"partial" et
produit l'effet attendu (une `Notification`, un `HlpTicket`) quand
l'evenement correspondant est publie via `core.events.publish_event`,
meme patron `transaction.atomic()` + `django_db(transaction=True)` que
`apps.automation.tests.test_dispatch` (indispensable pour que le
`transaction.on_commit` de `publish_event` se declenche reellement)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.db import transaction

from apps.automation.models import RUN_STATUS_PARTIAL, RUN_STATUS_SUCCESS, AutoRun
from apps.automation.services import engine
from apps.automation.services.seed_flows import seed_default_flows
from apps.core import events
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import HlpTicket
from apps.partners.tests.factories import PartnerFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(events, "sleep", lambda seconds: None)
    monkeypatch.setattr(engine, "sleep", lambda seconds: None)


def _user_with_role(tenant: Tenant, role_code: str, email: str) -> User:
    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name=role_code)
    user.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant)
    return user


def _last_run(tenant: Tenant, flow_name: str) -> AutoRun:
    with use_tenant(tenant.id):
        return AutoRun.objects.filter(flow__tenant=tenant, flow__name=flow_name).latest(
            "started_at"
        )


def test_seed_default_flows_creates_and_activates_a_large_flow_set() -> None:
    """Verification "de base" attendue par le plan INT4 : un jeu LARGE de
    flux est cree, tous actifs, et un second appel est parfaitement
    idempotent (aucun doublon, rien retouche)."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        results = seed_default_flows(tenant)
        assert len(results) >= 15
        assert all(created for _flow, created in results)
        assert all(flow.is_active for flow, _created in results)

        # Idempotence : second appel, plus aucune creation.
        results_again = seed_default_flows(tenant)
        assert all(not created for _flow, created in results_again)
        assert len(results_again) == len(results)


def test_purchase_order_confirmed_notifies_magasinier() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        magasinier = _user_with_role(tenant, "magasinier", "mag@example.com")
        seed_default_flows(tenant)

    with transaction.atomic():
        events.publish_event(
            "purchase.order_confirmed",
            {"order_id": "o1", "reference": "PO-001", "amount_total_mga": "150000"},
            tenant_id=str(tenant.id),
        )

    run = _last_run(tenant, "Commande fournisseur confirmee -> notifier magasinier")
    assert run.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=magasinier, notification_type="purchase.order_confirmed"
        ).exists()


def test_sales_order_blocked_notifies_direction_and_comptable() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        direction = _user_with_role(tenant, "direction", "dir@example.com")
        comptable = _user_with_role(tenant, "comptable", "cpt@example.com")
        seed_default_flows(tenant)

    with transaction.atomic():
        events.publish_event(
            "sales.order_blocked",
            {
                "order_id": "so1",
                "reference": "SO-001",
                "partner_id": "p1",
                "reason": "Encours depasse",
                "outstanding_amount_mga": "500000",
            },
            tenant_id=str(tenant.id),
        )

    run = _last_run(tenant, "Commande client bloquee (credit) -> notifier direction et comptable")
    assert run.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=direction, notification_type="sales.order_blocked"
        ).exists()
        assert Notification.objects.filter(
            user=comptable, notification_type="sales.order_blocked"
        ).exists()


def test_credoc_opened_condition_only_notifies_on_ouvert_state() -> None:
    """Demonstration de la CONDITION sur `payload['state']` : l'etat
    `"ouvert"` notifie, un autre etat (`"demande"`) ne notifie personne —
    meme flux, deux executions, deux comportements distincts."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        direction = _user_with_role(tenant, "direction", "dir-cd@example.com")
        comptable = _user_with_role(tenant, "comptable", "cpt-cd@example.com")
        seed_default_flows(tenant)

    with transaction.atomic():
        events.publish_event(
            "financing.credoc_state_changed",
            {"credoc_id": "c1", "reference": "CD-001", "state": "demande"},
            tenant_id=str(tenant.id),
        )
    run_demande = _last_run(tenant, "Credoc ouvert -> notifier direction et comptable")
    assert run_demande.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert not Notification.objects.filter(
            user=direction, notification_type="financing.credoc_state_changed"
        ).exists()

    with transaction.atomic():
        events.publish_event(
            "financing.credoc_state_changed",
            {"credoc_id": "c1", "reference": "CD-001", "state": "ouvert"},
            tenant_id=str(tenant.id),
        )
    run_ouvert = _last_run(tenant, "Credoc ouvert -> notifier direction et comptable")
    assert run_ouvert.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=direction, notification_type="financing.credoc_state_changed"
        ).exists()
        assert Notification.objects.filter(
            user=comptable, notification_type="financing.credoc_state_changed"
        ).exists()


def test_risk_flagged_routes_by_category_condition_branching() -> None:
    """Le flux le plus explicitement demande par le plan INT4 : une VRAIE
    branche conditionnelle sur `payload['category']` — fournisseur ->
    acheteur, financier -> comptable+direction, une categorie non geree
    (production) -> aucune notification."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        acheteur = _user_with_role(tenant, "acheteur", "ach-rsk@example.com")
        resp_production = _user_with_role(tenant, "resp_production", "rp-rsk@example.com")
        comptable = _user_with_role(tenant, "comptable", "cpt-rsk@example.com")
        direction = _user_with_role(tenant, "direction", "dir-rsk@example.com")
        seed_default_flows(tenant)

    with transaction.atomic():
        events.publish_event(
            "risk.flagged",
            {"risk_item_id": "r1", "category": "fournisseur", "score": 20},
            tenant_id=str(tenant.id),
        )
    run_supplier = _last_run(tenant, "Risque signale (score eleve) -> routage par categorie")
    assert run_supplier.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(user=acheteur, notification_type="risk.flagged").exists()
        assert not Notification.objects.filter(
            user=resp_production, notification_type="risk.flagged"
        ).exists()

    with transaction.atomic():
        events.publish_event(
            "risk.flagged",
            {"risk_item_id": "r2", "category": "financier", "score": 22},
            tenant_id=str(tenant.id),
        )
    run_financial = _last_run(tenant, "Risque signale (score eleve) -> routage par categorie")
    assert run_financial.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=comptable, notification_type="risk.flagged"
        ).exists()
        assert Notification.objects.filter(
            user=direction, notification_type="risk.flagged"
        ).exists()

    with transaction.atomic():
        events.publish_event(
            "risk.flagged",
            {"risk_item_id": "r3", "category": "production", "score": 24},
            tenant_id=str(tenant.id),
        )
    run_other = _last_run(tenant, "Risque signale (score eleve) -> routage par categorie")
    assert run_other.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        # Categorie non geree par les 3 branches : aucune notification
        # supplementaire par rapport aux deux runs precedents.
        assert Notification.objects.filter(notification_type="risk.flagged").count() == 3


def test_ai_anomaly_detected_creates_helpdesk_ticket_and_notifies_direction() -> None:
    """Le flux `helpdesk.create_ticket_from_event` explicitement demande
    par le plan INT4 : verifie un vrai `HlpTicket` cree EN PLUS de la
    notification, avec le repli "premier superutilisateur" deja en place
    (cf. apps.helpdesk.services.automation_registration)."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        direction = _user_with_role(tenant, "direction", "dir-ai@example.com")
        UserFactory(is_superuser=True)
        seed_default_flows(tenant)

    with transaction.atomic():
        events.publish_event(
            "ai.anomaly_detected",
            {
                "anomaly_id": "an1",
                "check_code": "stock.negative",
                "severity": "high",
                "content_type_label": None,
                "object_id": None,
            },
            tenant_id=str(tenant.id),
        )

    run = _last_run(tenant, "Anomalie IA detectee -> ticket + notifier direction")
    assert run.status == RUN_STATUS_SUCCESS
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=direction, notification_type="ai.anomaly_detected"
        ).exists()
        assert HlpTicket.objects.filter(
            tenant=tenant, subject="Anomalie IA detectee automatiquement"
        ).exists()


def test_purchase_dispute_opened_notifies_and_opens_incident() -> None:
    """Couvre le second flux `purchase.dispute_opened` (l'action metier
    `purchase.open_incident`, au-dela de la simple notification) — les deux
    flux crees pour ce meme `event_type` s'executent independamment."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        acheteur = _user_with_role(tenant, "acheteur", "ach-dsp@example.com")
        seed_default_flows(tenant)

    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant)

    with transaction.atomic():
        events.publish_event(
            "purchase.dispute_opened",
            {
                "order_id": "po1",
                "reference": "PO-DSP-1",
                "partner_id": str(partner.id),
                "reason": "Marchandise non conforme",
            },
            tenant_id=str(tenant.id),
        )

    run_notify = _last_run(tenant, "Litige fournisseur ouvert -> notifier acheteur et direction")
    assert run_notify.status in (RUN_STATUS_SUCCESS, RUN_STATUS_PARTIAL)
    run_incident = _last_run(tenant, "Litige fournisseur ouvert -> ouvrir un incident fournisseur")
    assert run_incident.status in (RUN_STATUS_SUCCESS, RUN_STATUS_PARTIAL)
    with use_tenant(tenant.id):
        assert Notification.objects.filter(
            user=acheteur, notification_type="purchase.dispute_opened"
        ).exists()
