"""HD6 : test d'integration bout-en-bout du chantier `helpdesk` complet
(HD1-HD5), chainant les VRAIES fonctions de service (jamais un test unitaire
isole par etape) — meme lecon deja documentee dans ce depot (chantier `mrp`,
« toujours ecrire le test d'integration qui rejoue le scenario complet »).

Rejoue exactement le scenario « Vérification de fin de chantier » §7 du
plan : creation d'un ticket rattache a un enregistrement operationnel
(`purchase.PurOrder`, via le pre-filtrage `HlpTicketTypeCatalog.
related_content_type`), assignation, echange par chat interne, breche de
SLA, escalade automatique + notification, resolution, cloture, enquete
CSAT, rapport combine — PUIS declenchement de la creation automatique de
ticket depuis un evenement (`helpdesk.create_ticket_from_event`, LE
mecanisme de « connexion native aux operations »)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.chat.services.public import get_or_create_document_channel
from apps.core.models.tenant import Tenant
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import (
    KIND_INCIDENT,
    HlpCsatResponse,
    HlpEscalationEvent,
    HlpEscalationRule,
    HlpSlaBreach,
    HlpTicket,
)
from apps.helpdesk.services.csat import submit_csat_response
from apps.helpdesk.services.escalation import run_escalation_checks
from apps.helpdesk.services.reports import (
    agent_performance_report,
    csat_summary,
    sla_compliance_report,
    team_benchmark_report,
)
from apps.helpdesk.services.sla import check_breaches
from apps.helpdesk.services.tickets import (
    add_comment,
    assign_ticket,
    close_ticket,
    create_ticket,
    resolve_ticket,
)
from apps.helpdesk.tests.factories import HlpEscalationRuleFactory, HlpSlaPolicyFactory
from apps.purchase.tests.factories import PurOrderFactory

pytestmark = pytest.mark.django_db


def test_full_ticket_lifecycle_from_operational_link_to_csat_and_reports() -> None:
    tenant = Tenant.objects.create(code="HLP-E2E", name="Helpdesk E2E Tenant")
    with use_tenant(tenant.id):
        requester = UserFactory()
        agent = UserFactory()

        # 1. Un enregistrement operationnel deja existant (commande
        # fournisseur en retard) — le ticket s'y rattache par le lien
        # generique `content_type`/`object_id`, exactement le scenario
        # « Retard de livraison fournisseur » du plan.
        late_order = PurOrderFactory(tenant=tenant)

        # 2. Une politique SLA tres courte, pour pouvoir la breacher au
        # sein du test sans attendre reellement.
        sla_policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=30, resolution_minutes=60
        )

        ticket = create_ticket(
            tenant,
            subject="Retard de livraison fournisseur",
            requester=requester,
            kind=KIND_INCIDENT,
            sla_policy=sla_policy,
            content_object=late_order,
        )
        assert ticket.content_type_id == ContentType.objects.get_for_model(late_order.__class__).id
        assert ticket.object_id == str(late_order.pk)
        assert ticket.first_response_due_at is not None
        assert ticket.resolution_due_at is not None

        # 3. Assignation.
        ticket = assign_ticket(ticket, agent, assignee=agent)
        assert ticket.state == HlpTicket.STATE_IN_PROGRESS
        assert ticket.assignee_id == agent.id

        # 4. Chat interne integre au ticket (reutilisation `chat`, aucun
        # nouveau modele/mecanisme temps reel).
        channel_id = get_or_create_document_channel(
            tenant=tenant, content_object=ticket, participants=[requester, agent]
        )
        assert channel_id
        # Idempotent : un second appel retrouve le MEME canal.
        assert (
            get_or_create_document_channel(
                tenant=tenant, content_object=ticket, participants=[requester, agent]
            )
            == channel_id
        )

        # 5. Un commentaire non-interne de l'agent positionne
        # `first_responded_at` — mais on force volontairement les
        # echeances dans le passe AVANT de commenter pour pouvoir breacher
        # la premiere reponse malgre tout (cf. etape 6).
        ticket.first_response_due_at = timezone.now() - timedelta(minutes=5)
        ticket.resolution_due_at = timezone.now() + timedelta(days=1)
        ticket.save(update_fields=["first_response_due_at", "resolution_due_at"])

        # 6. Breche de SLA (premiere reponse en retard) detectee par la
        # commande de management sous-jacente (`sla.check_breaches`),
        # idempotente au deuxieme passage.
        breaches = check_breaches(tenant)
        assert len(breaches) == 1
        assert breaches[0].breach_type == HlpSlaBreach.BREACH_FIRST_RESPONSE
        assert HlpSlaBreach.objects.filter(ticket=ticket).count() == 1
        assert check_breaches(tenant) == []  # jamais un doublon

        ticket.refresh_from_db()
        assert ticket.risk_score > 0  # recalcule par la meme passe

        # 7. Escalade AUTOMATIQUE : une regle "breche de SLA" matche le
        # ticket, l'escalade, notifie et publie
        # `"helpdesk.ticket_escalated"` — sans aucune intervention humaine.
        rule = HlpEscalationRuleFactory(
            tenant=tenant, condition_type=HlpEscalationRule.CONDITION_SLA_BREACH
        )
        events = run_escalation_checks(tenant)
        assert len(events) == 1
        assert events[0].rule_id == rule.id
        assert events[0].escalated_by is None  # automatique, cf. docstring du modele

        ticket.refresh_from_db()
        assert ticket.state == HlpTicket.STATE_ESCALATED
        assert HlpEscalationEvent.objects.filter(ticket=ticket, rule=rule).count() == 1
        # Jamais deux fois la meme regle sur le meme ticket.
        assert run_escalation_checks(tenant) == []

        # 8. L'agent repond enfin (positionne `first_responded_at`), puis
        # resout et cloture le ticket.
        add_comment(ticket, author=agent, body="Fournisseur relance, livraison reprogrammee.")
        ticket.refresh_from_db()
        assert ticket.first_responded_at is not None

        ticket = resolve_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_RESOLVED
        ticket = close_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_CLOSED

        # 9. Enquete CSAT post-resolution.
        csat = submit_csat_response(ticket, score=4, comment="Resolu correctement, un peu lent.")
        assert isinstance(csat, HlpCsatResponse)
        assert HlpCsatResponse.objects.filter(ticket=ticket).count() == 1
        with pytest.raises(ValidationError):  # une seconde soumission est refusee
            submit_csat_response(ticket, score=5)

        # 10. Rapport combine (CSAT + performance agents + benchmarking
        # equipe + conformite SLA) — calcule a la volee, aucun nouveau
        # modele de reporting.
        summary = csat_summary(tenant)
        assert summary["response_count"] == 1
        assert summary["average_score"] == 4

        agent_rows = agent_performance_report(tenant)
        assert any(row["assignee_id"] == str(agent.id) for row in agent_rows)

        team_rows = team_benchmark_report(tenant)
        assert team_rows == []  # aucune equipe assignee sur ce ticket, disclosed

        compliance = sla_compliance_report(tenant)
        assert compliance["breach_count"] >= 1


def test_automation_registry_creates_ticket_natively_from_an_operational_event() -> None:
    """LE mecanisme de « connexion native aux operations » (cf. plan,
    section dediee) : le Studio de workflow visuel resout l'action
    enregistree de facon totalement generique (`get_registered_action`) —
    on reproduit ici exactement cet appel, sans jamais importer
    `_create_ticket_from_event` directement, pour verifier que
    l'enregistrement cote registre partage est bien le point d'entree
    reellement utilisable par le moteur."""
    tenant = Tenant.objects.create(code="HLP-E2E-AUTO", name="Helpdesk E2E Automation Tenant")
    with use_tenant(tenant.id):
        superuser = UserFactory(is_superuser=True)
        order = PurOrderFactory(tenant=tenant)
        order_content_type = ContentType.objects.get_for_model(order.__class__)

        registered = get_registered_action("helpdesk.create_ticket_from_event")
        assert registered is not None

        reference = registered.function(
            str(tenant.id),
            {
                "subject": "Anomalie IA detectee sur commande fournisseur",
                "content_type_label": f"{order_content_type.app_label}.{order_content_type.model}",
                "object_id": str(order.pk),
            },
        )

        ticket = HlpTicket.objects.get(reference=reference)
        assert ticket.kind == KIND_INCIDENT
        assert ticket.requester_id == superuser.id
        assert ticket.content_type_id == order_content_type.id
        assert ticket.object_id == str(order.pk)
