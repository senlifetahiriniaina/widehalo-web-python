"""WA-1/WA-2 (L10) — le message entrant existe enfin, et « STOP » desabonne.

Deux defauts qui se renforcaient l'un l'autre.

**Le message entrant etait invisible.**
`core.services.notifications.record_inbound_whatsapp_message` n'acceptait
aucun tenant et laissait donc `tenant_id` a NULL, alors que le webhook
gouverne avait resolu le tenant douze lignes plus haut. L'ecran de
conversation filtre `WhatsAppMessage.objects.filter(tenant_id=...)` :
AUCUNE ligne entrante ne pouvait jamais correspondre. Ce que le client
ecrivait — son choix de menu, une reclamation — etait enregistre en base et
invisible de tous les ecrans, pour tous les tenants.

**« STOP » ne desabonnait personne.** `handle_inbound_message` ne
reconnaissait que « 1 », « 2 », « 3 » et n'importait meme pas
`revoke_consent`. Un client qui repondait « STOP » voyait son message
classe en reponse inconnue, son consentement restait actif, et les
campagnes continuaient de lui parvenir.

Ensemble : le client demandait a etre desabonne, personne ne le voyait, et
rien ne se passait. C'est le scenario que ces tests ferment.
"""

from __future__ import annotations

import pytest

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.services.notifications import record_inbound_whatsapp_message
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaConversation
from apps.whatsapp.services.consent import grant_consent, has_active_consent
from apps.whatsapp.services.inbound import UNSUBSCRIBE_KEYWORDS, handle_inbound_message

pytestmark = pytest.mark.django_db

PHONE = "+261340000001"


@pytest.fixture
def wa_tenant() -> Tenant:
    return Tenant.objects.create(code="WA-L10", name="WhatsApp L10 Tenant")


def test_an_inbound_message_is_recorded_under_its_tenant(wa_tenant: Tenant) -> None:
    """Sans `tenant_id`, le message n'apparait sur aucun ecran — l'ecran de
    conversation filtre par tenant."""
    with use_tenant(wa_tenant.id):
        message = record_inbound_whatsapp_message(
            phone_number=PHONE,
            body="Bonjour",
            provider_message_id="wamid.1",
            tenant_id=wa_tenant.id,
        )

        assert message.tenant_id == wa_tenant.id
        # C'est exactement le filtre de `apps/whatsapp/views.py`.
        assert WhatsAppMessage.objects.filter(tenant_id=wa_tenant.id, phone_number=PHONE).exists()


def test_an_inbound_message_without_a_tenant_is_still_kept(wa_tenant: Tenant) -> None:
    """Cas degrade explicite : sans `WHATSAPP_DEFAULT_TENANT_ID`, le webhook
    n'a aucun tenant a fournir. Perdre le message serait pire que
    l'enregistrer orphelin — mais ce n'est plus le comportement normal."""
    with use_tenant(wa_tenant.id):
        message = record_inbound_whatsapp_message(
            phone_number=PHONE, body="Bonjour", provider_message_id="wamid.2"
        )

        assert message.tenant_id is None


@pytest.mark.parametrize("keyword", sorted(UNSUBSCRIBE_KEYWORDS))
def test_every_unsubscribe_keyword_revokes_consent(wa_tenant: Tenant, keyword: str) -> None:
    """Chaque mot-cle de la liste bornee doit reellement desabonner — une
    liste dont un membre ne fonctionnerait pas serait pire qu'une liste
    plus courte."""
    with use_tenant(wa_tenant.id):
        grant_consent(wa_tenant, phone_number=PHONE, source="test")
        assert has_active_consent(wa_tenant, PHONE) is True

        handle_inbound_message(wa_tenant, phone_number=PHONE, body=keyword)

        assert has_active_consent(wa_tenant, PHONE) is False


def test_unsubscribe_is_case_and_space_insensitive(wa_tenant: Tenant) -> None:
    with use_tenant(wa_tenant.id):
        grant_consent(wa_tenant, phone_number=PHONE, source="test")

        handle_inbound_message(wa_tenant, phone_number=PHONE, body="  Stop  ")

        assert has_active_consent(wa_tenant, PHONE) is False


def test_an_approximate_word_does_not_unsubscribe(wa_tenant: Tenant) -> None:
    """La liste est bornee, jamais une comprehension approximative : un
    desabonnement decide sur une approximation serait aussi grave qu'un
    desabonnement manque."""
    with use_tenant(wa_tenant.id):
        grant_consent(wa_tenant, phone_number=PHONE, source="test")

        handle_inbound_message(wa_tenant, phone_number=PHONE, body="je veux stopper")

        assert has_active_consent(wa_tenant, PHONE) is True


def test_an_unsubscribe_never_triggers_the_intent_menu(wa_tenant: Tenant) -> None:
    """Repondre a « STOP » par un menu d'intentions serait exactement le
    message que le client vient de refuser."""
    with use_tenant(wa_tenant.id):
        grant_consent(wa_tenant, phone_number=PHONE, source="test")

        conversation = handle_inbound_message(wa_tenant, phone_number=PHONE, body="STOP")

        assert conversation.intent_state == WaConversation.INTENT_NONE
        assert has_active_consent(wa_tenant, PHONE) is False


def test_an_ordinary_message_still_goes_through_the_menu(wa_tenant: Tenant) -> None:
    """La regle du desabonnement ne doit pas court-circuiter le flux
    normal : un message ordinaire suit toujours son chemin WA-8."""
    with use_tenant(wa_tenant.id):
        grant_consent(wa_tenant, phone_number=PHONE, source="test")

        conversation = handle_inbound_message(wa_tenant, phone_number=PHONE, body="Bonjour")

        assert has_active_consent(wa_tenant, PHONE) is True
        assert conversation.last_inbound_at is not None
