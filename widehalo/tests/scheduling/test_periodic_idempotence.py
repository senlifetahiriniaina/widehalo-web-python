"""L0-1 — invariant transverse : deux exécutions consécutives, un seul effet.

Ce fichier existe parce que brancher un ordonnanceur sur des commandes qui ne
sont pas idempotentes ne les rend pas utiles, il les rend nuisibles. Cinq
commandes du dépôt produisaient un doublon à chaque exécution : tant que rien
ne les déclenchait, le défaut restait théorique — c'est précisément ce que
l'audit relève au §3.1 (« rien n'ordonnance rien »).

L'invariant vérifié ici est le préalable de sûreté du lot L0 : chaque
traitement périodique doit pouvoir tourner deux fois de suite sans produire
deux fois son effet. Il est testé avant que l'ordonnanceur n'existe, pas
après.
"""

from __future__ import annotations

import pytest
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_expiry_alert_does_not_renotify_the_same_lot() -> None:
    """`run_expiry_alerts` renotifiait un lot périmant à chaque passage."""
    from apps.core.models.notification import Notification
    from apps.stocks.services.expiry_alerts import check_expiring_lots

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        check_expiring_lots(tenant)
        first = Notification.objects.filter(notification_type="stocks.lot_expiring").count()
        check_expiring_lots(tenant)
        second = Notification.objects.filter(notification_type="stocks.lot_expiring").count()
    assert first == second


def test_overdue_control_alert_does_not_renotify_the_same_control() -> None:
    """`run_quality_control_checks` : un contrôle en retard le reste jusqu'à
    ce qu'il soit fait."""
    from apps.core.models.notification import Notification
    from apps.quality.services.alerts import check_overdue_controls

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        check_overdue_controls(tenant)
        first = Notification.objects.filter(notification_type="quality.control_overdue").count()
        check_overdue_controls(tenant)
        second = Notification.objects.filter(notification_type="quality.control_overdue").count()
    assert first == second


def test_reordering_does_not_recreate_a_pending_proposal() -> None:
    """Le cas le plus coûteux : une proposition ET une demande d'approbation
    à chaque exécution, jusqu'à la réception réelle des marchandises.

    Le scénario est monté avec une règle qui se déclenche RÉELLEMENT — une
    vérification sur un tenant vide passerait sans rien prouver."""
    import uuid
    from decimal import Decimal

    from apps.core.models.user import User
    from apps.purchase.models import PurReorderingProposal
    from apps.purchase.services.reordering import create_reordering_rule, run_reordering

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        User.objects.create_superuser(
            email=f"reorder-{uuid.uuid4().hex[:8]}@example.com", password="Str0ngPassw0rd!23"
        )
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(10), max_qty=Decimal(50)
        )

        first_run = run_reordering(tenant)
        # La règle se déclenche vraiment : sans cette assertion, le test
        # passerait aussi sur un dépôt où plus rien ne fonctionne.
        assert len(first_run) == 1
        first = PurReorderingProposal.objects.count()

        second_run = run_reordering(tenant)
        assert second_run == []
        second = PurReorderingProposal.objects.count()

    assert first == second == 1


def test_anomaly_detection_does_not_recreate_a_standing_anomaly() -> None:
    """Une anomalie recréée quotidiennement déclenche, en sévérité haute, un
    appel au modèle de langage à chaque fois : le coût est facturé."""
    from apps.ai.models import AiAnomaly
    from apps.ai.services.anomaly_detection import run_all_checks

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        run_all_checks(tenant)
        first = AiAnomaly.objects.count()
        run_all_checks(tenant)
        second = AiAnomaly.objects.count()
    assert first == second


def test_insight_generation_does_not_recreate_the_same_insight() -> None:
    from apps.ai.models import AiInsight
    from apps.ai.services.automated_insights import generate

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        generate(tenant)
        first = AiInsight.objects.count()
        generate(tenant)
        second = AiInsight.objects.count()
    assert first == second
