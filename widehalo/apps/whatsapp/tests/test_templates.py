"""WA-3 (cahier Phase 2 §13.4) : bibliothèque de modèles avec statut
d'approbation."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaMessageTemplate
from apps.whatsapp.services.templates import (
    approve_template,
    create_template,
    get_approved_template,
    reject_template,
    render_body,
    submit_for_review,
)

pytestmark = pytest.mark.django_db


def test_new_template_starts_as_draft_and_is_not_approved() -> None:
    tenant = Tenant.objects.create(code="WA-T1", name="WhatsApp Template Tenant 1")
    with use_tenant(tenant.id):
        template = create_template(
            tenant,
            code="bienvenue",
            name="Bienvenue",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="Bonjour {{nom_client}}",
        )
        assert template.status == WaMessageTemplate.STATUS_DRAFT
        assert get_approved_template(tenant, "bienvenue") is None


def test_full_review_cycle_draft_to_approved() -> None:
    tenant = Tenant.objects.create(code="WA-T2", name="WhatsApp Template Tenant 2")
    with use_tenant(tenant.id):
        reviewer = UserFactory()
        template = create_template(
            tenant,
            code="confirmation",
            name="Confirmation de commande",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="Commande confirmée",
        )
        submit_for_review(template)
        assert template.status == WaMessageTemplate.STATUS_PENDING_REVIEW

        approve_template(template, user=reviewer)
        assert template.status == WaMessageTemplate.STATUS_APPROVED
        assert template.reviewed_by_id == reviewer.id
        assert get_approved_template(tenant, "confirmation") is not None


def test_cannot_approve_a_template_not_pending_review() -> None:
    tenant = Tenant.objects.create(code="WA-T3", name="WhatsApp Template Tenant 3")
    with use_tenant(tenant.id):
        reviewer = UserFactory()
        template = create_template(
            tenant,
            code="brouillon",
            name="Brouillon",
            category=WaMessageTemplate.CATEGORY_MARKETING,
            body_text="...",
        )
        with pytest.raises(ValidationError):
            approve_template(template, user=reviewer)


def test_reject_requires_a_reason_and_can_be_resubmitted() -> None:
    tenant = Tenant.objects.create(code="WA-T4", name="WhatsApp Template Tenant 4")
    with use_tenant(tenant.id):
        reviewer = UserFactory()
        template = create_template(
            tenant,
            code="promo",
            name="Promo",
            category=WaMessageTemplate.CATEGORY_MARKETING,
            body_text="Promo -20%",
        )
        submit_for_review(template)
        with pytest.raises(ValidationError):
            reject_template(template, user=reviewer, reason="")

        reject_template(template, user=reviewer, reason="Ton non conforme")
        assert template.status == WaMessageTemplate.STATUS_REJECTED
        assert template.rejection_reason == "Ton non conforme"

        # Un modele rejete peut etre resoumis (nouvelle iteration).
        submit_for_review(template)
        assert template.status == WaMessageTemplate.STATUS_PENDING_REVIEW


def test_render_body_substitutes_declared_variables_only() -> None:
    tenant = Tenant.objects.create(code="WA-T5", name="WhatsApp Template Tenant 5")
    with use_tenant(tenant.id):
        template = create_template(
            tenant,
            code="livraison",
            name="Livraison",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="Bonjour {{nom_client}}, colis {{numero}} livré.",
            variables=["nom_client", "numero"],
        )
        rendered = render_body(template, {"nom_client": "Rina", "numero": "CMD-42"})
        assert rendered == "Bonjour Rina, colis CMD-42 livré."
