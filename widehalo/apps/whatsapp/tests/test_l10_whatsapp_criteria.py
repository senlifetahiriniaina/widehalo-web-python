"""L10 — WhatsApp : la file qui n'existait pas, le plafond qui ne protégeait
que la facture, et un envoi qui ne laissait aucune trace.

**WA-7.** « Envois en file avec état visible et repris automatiquement. »
Aucune de ces trois choses n'était vraie. L'envoi était synchrone : le
client réseau était appelé dans le thread de la requête HTTP et la ligne
n'était écrite qu'après, statut déjà résolu. `STATUS_PENDING` existait sur
le modèle sans être l'état d'aucun message réel. Et `retry_failed_messages`,
avec son backoff 5 min / 30 min / 2 h, avait exactement deux appelants : un
endpoint d'API et un bouton d'écran — « automatiquement » voulait dire
« quand quelqu'un y pense ». `apps/whatsapp/` n'avait aucun répertoire
`management/`, et le registre d'ordonnancement comptait dix-neuf commandes,
aucune WhatsApp.

**WA-5.** Le plafond mensuel de coût existait et fonctionnait. La limite de
fréquence par destinataire — la seconde moitié du critère — n'existait pas.
Les deux ne protègent pas le même objet : cent messages au même numéro
coûtent exactement autant que cent messages à cent numéros, et c'est le
premier cas qui est un harcèlement.

**Le défaut que l'audit ne relevait pas.** `_maybe_send_intent_menu` (WA-8)
envoyait le menu d'accueil par le client brut sans créer aucune ligne
`WhatsAppMessage`. Ce message partait réellement au client : invisible du
journal, invisible de l'écran de conversation, et compté pour zéro au
plafond comme à la limite de fréquence. Son exemption portait sur le
consentement — elle avait été étendue en pratique à la traçabilité, ce que
rien ne justifiait."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent, revoke_consent
from apps.whatsapp.services.messaging import (
    flush_pending_messages,
    process_outbound_queue,
    queue_governed_template_message,
)
from apps.whatsapp.services.templates import approve_template, create_template, submit_for_review

pytestmark = pytest.mark.django_db

PHONE = "+261340000001"


@dataclass
class _FakeSendResult:
    status: str
    provider_message_id: str = ""
    details: str = ""


class _FakeSucceedingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_template(self, phone_number, template_name, params):
        self.calls.append((phone_number, template_name))
        return _FakeSendResult(status="sent", provider_message_id="wamid.fake")


class _FakeFailingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_template(self, phone_number, template_name, params):
        self.calls.append((phone_number, template_name))
        return _FakeSendResult(status="failed", details="canal indisponible")


class _ExplodingClient:
    """Tout appel réseau depuis ce client est une erreur de conception : il
    sert à prouver qu'une mise en file NE TOUCHE PAS au réseau."""

    def send_template(self, phone_number, template_name, params):
        raise AssertionError("Appel réseau pendant la mise en file : l'envoi est resté synchrone.")


@pytest.fixture
def wa_setup():
    tenant = Tenant.objects.create(code="L10-WA", name="WhatsApp L10 SARL")
    with use_tenant(tenant.id):
        user = UserFactory()
        template = create_template(
            tenant,
            code="relance",
            name="Relance",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="Bonjour {{nom}}",
            variables=["nom"],
            estimated_cost_ariary=Decimal("50"),
        )
        submit_for_review(template)
        approve_template(template, user=user)
        grant_consent(tenant, phone_number=PHONE, source="test", granted_by=user)
    return tenant, user, template


def _queue(tenant, user, *, phone=PHONE, variables=None):
    return queue_governed_template_message(
        tenant,
        phone_number=phone,
        template_code="relance",
        variables=variables if variables is not None else {"nom": "Rakoto"},
        user=user,
    )


# --- WA-7 : la file ------------------------------------------------------------


def test_queueing_does_not_touch_the_network(wa_setup, monkeypatch) -> None:
    """Le cœur de WA-7. Avant L10, cette fonction n'existait pas et la
    surface d'envoi appelait le réseau dans le thread de la requête : canal
    indisponible = échec affiché à l'utilisateur et message perdu."""
    tenant, user, _template = wa_setup
    monkeypatch.setattr(
        "apps.core.services.whatsapp.get_whatsapp_client", lambda: _ExplodingClient()
    )
    with use_tenant(tenant.id):
        message = _queue(tenant, user)

    assert message.status == WhatsAppMessage.STATUS_PENDING
    assert message.provider_message_id == ""
    # L'état est VISIBLE : la ligne existe, avec son modèle, son coût et son
    # corps rendu — pas un envoi disparu en attendant un traitement.
    assert message.template_name == "relance"
    assert message.cost_ariary == Decimal("50")
    assert message.body == "Bonjour Rakoto"


def test_the_queue_is_emptied_by_the_periodic_pass(wa_setup, monkeypatch) -> None:
    tenant, user, _template = wa_setup
    client = _FakeSucceedingClient()
    monkeypatch.setattr("apps.core.services.whatsapp.get_whatsapp_client", lambda: client)

    with use_tenant(tenant.id):
        message = _queue(tenant, user)
        sent = flush_pending_messages(tenant)

    assert [m.id for m in sent] == [message.id]
    message.refresh_from_db()
    assert message.status == WhatsAppMessage.STATUS_SENT
    assert message.provider_message_id == "wamid.fake"
    assert client.calls == [(PHONE, "relance")]


def test_a_consent_revoked_after_queueing_stops_the_send(wa_setup, monkeypatch) -> None:
    """WA-2 exige que la révocation soit « effective immédiatement ». Une
    file qui ne revalide qu'à la mise en file transformerait chaque message
    en attente en un envoi que plus rien n'autorise."""
    tenant, user, _template = wa_setup
    client = _FakeSucceedingClient()
    monkeypatch.setattr("apps.core.services.whatsapp.get_whatsapp_client", lambda: client)

    with use_tenant(tenant.id):
        message = _queue(tenant, user)
        revoke_consent(tenant, phone_number=PHONE)
        sent = flush_pending_messages(tenant)

    assert sent == []
    assert client.calls == [], "Le message est parti malgré la révocation."
    message.refresh_from_db()
    assert message.status == WhatsAppMessage.STATUS_FAILED
    # Le MOTIF est écrit : « refusé parce que le consentement a été retiré »
    # et « jamais parti, on ne sait pas pourquoi » sont deux états qu'un
    # exploitant doit pouvoir distinguer.
    assert "consentement" in message.error_message.lower()
    # Un refus de gouvernance n'entre pas dans le cycle de reprise : le
    # represéenter reviendrait à réessayer sans fin un envoi interdit.
    assert message.next_retry_at is None
    assert message.retry_count == 0


def test_a_network_failure_does_enter_the_retry_cycle(wa_setup, monkeypatch) -> None:
    """La contrepartie du test précédent : une panne réseau, elle, doit
    être reprise. Sans cette distinction, « refusé » et « en panne »
    seraient traités pareil et l'un des deux serait mal servi."""
    tenant, user, _template = wa_setup
    monkeypatch.setattr(
        "apps.core.services.whatsapp.get_whatsapp_client", lambda: _FakeFailingClient()
    )
    with use_tenant(tenant.id):
        message = _queue(tenant, user)
        flush_pending_messages(tenant)

    message.refresh_from_db()
    assert message.status == WhatsAppMessage.STATUS_FAILED
    assert message.error_message == ""
    assert message.next_retry_at is not None


def test_the_periodic_command_is_declared_in_the_scheduling_registry() -> None:
    """`retry_failed_messages` existait avec son backoff depuis le lot
    initial et n'avait AUCUN déclencheur automatique : deux appelants, un
    endpoint et un bouton. La garde `test_scheduled_commands_declared` ne
    pouvait pas le voir — elle vérifie que toute commande présente sur
    disque est planifiée, et `apps/whatsapp/` n'avait pas de répertoire
    `management/` du tout. L'absence ne déclenche rien."""
    from apps.core.services.scheduled_commands import get_scheduled_command

    declared = get_scheduled_command("whatsapp.outbound_queue")
    assert declared is not None, "La file WhatsApp n'a toujours aucun déclencheur automatique."
    assert declared.command == "run_whatsapp_queue"
    assert declared.module == "whatsapp"


def test_the_command_runs_the_queue_for_every_tenant(wa_setup, monkeypatch) -> None:
    from django.core.management import call_command

    tenant, user, _template = wa_setup
    monkeypatch.setattr(
        "apps.core.services.whatsapp.get_whatsapp_client", lambda: _FakeSucceedingClient()
    )
    with use_tenant(tenant.id):
        message = _queue(tenant, user)

    call_command("run_whatsapp_queue")

    message.refresh_from_db()
    assert message.status == WhatsAppMessage.STATUS_SENT


def test_the_queue_pass_is_idempotent(wa_setup, monkeypatch) -> None:
    """L0-1 : un second passage ne doit jamais renvoyer le même message."""
    tenant, user, _template = wa_setup
    client = _FakeSucceedingClient()
    monkeypatch.setattr("apps.core.services.whatsapp.get_whatsapp_client", lambda: client)

    with use_tenant(tenant.id):
        _queue(tenant, user)
        first = process_outbound_queue(tenant)
        second = process_outbound_queue(tenant)

    assert first == {"sent": 1, "retried": 0}
    assert second == {"sent": 0, "retried": 0}
    assert len(client.calls) == 1


# --- WA-5 : la limite par destinataire -----------------------------------------


def test_the_same_recipient_cannot_be_flooded(wa_setup) -> None:
    """Le plafond mensuel de coût ne voit pas ce cas : cent messages à un
    seul numéro coûtent autant que cent messages à cent numéros."""
    tenant, user, _template = wa_setup
    tenant.whatsapp_max_messages_per_recipient_per_day = 3
    tenant.whatsapp_monthly_cost_cap_ariary = None  # aucun plafond de coût
    tenant.save(
        update_fields=[
            "whatsapp_max_messages_per_recipient_per_day",
            "whatsapp_monthly_cost_cap_ariary",
        ]
    )

    with use_tenant(tenant.id):
        for _ in range(3):
            _queue(tenant, user)
        with pytest.raises(ValidationError, match="fréquence"):
            _queue(tenant, user)


def test_the_limit_is_per_recipient_not_per_tenant(wa_setup) -> None:
    """La falsification qui compte : un compteur global par tenant
    satisferait aussi le test précédent, tout en bloquant un tenant qui
    écrit à des personnes différentes — ce que le critère ne demande pas."""
    tenant, user, _template = wa_setup
    other_phone = "+261340000002"
    tenant.whatsapp_max_messages_per_recipient_per_day = 2
    tenant.save(update_fields=["whatsapp_max_messages_per_recipient_per_day"])

    with use_tenant(tenant.id):
        grant_consent(tenant, phone_number=other_phone, source="test", granted_by=user)
        for _ in range(2):
            _queue(tenant, user)
        # Le premier destinataire est saturé...
        with pytest.raises(ValidationError):
            _queue(tenant, user)
        # ...le second ne l'est pas.
        message = _queue(tenant, user, phone=other_phone)

    assert message.phone_number == other_phone


def test_the_window_is_rolling_not_the_calendar_day(wa_setup) -> None:
    """Une journée civile se réinitialise à minuit : une boucle émettrait
    son quota deux fois à quelques minutes d'intervalle de part et d'autre
    de minuit — exactement ce que cette limite existe pour arrêter."""
    from apps.whatsapp.services.usage import messages_sent_to_recipient_today

    tenant, user, _template = wa_setup
    with use_tenant(tenant.id):
        message = _queue(tenant, user)
        # Message vieux de 25 h : hors fenêtre glissante.
        WhatsAppMessage.objects.filter(id=message.id).update(
            created_at=timezone.now() - dt.timedelta(hours=25)
        )
        assert messages_sent_to_recipient_today(tenant, PHONE) == 0

        WhatsAppMessage.objects.filter(id=message.id).update(
            created_at=timezone.now() - dt.timedelta(hours=23)
        )
        assert messages_sent_to_recipient_today(tenant, PHONE) == 1


def test_a_tenant_without_a_configured_limit_is_never_blocked(wa_setup) -> None:
    """Même discipline que le plafond de coût : l'absence de configuration
    ne doit jamais bloquer l'utilisateur."""
    tenant, user, _template = wa_setup
    tenant.whatsapp_max_messages_per_recipient_per_day = None
    tenant.save(update_fields=["whatsapp_max_messages_per_recipient_per_day"])

    with use_tenant(tenant.id):
        for _ in range(25):
            _queue(tenant, user)

    assert WhatsAppMessage.objects.filter(tenant_id=tenant.id, phone_number=PHONE).count() == 25


# --- WA-4/WA-8 : le menu d'intentions laissait le journal muet -----------------


def test_the_intent_menu_is_journalled_like_any_other_send(wa_setup, monkeypatch) -> None:
    """Ce message partait RÉELLEMENT au client sans créer aucune ligne :
    invisible du journal des échanges, invisible de l'écran de
    conversation, et compté pour zéro au plafond de coût comme à la limite
    de fréquence. Ne pas exiger un consentement (WA-8, réponse dans la
    fenêtre de service) n'est pas une raison de ne pas écrire ce qu'on a
    envoyé."""
    from apps.whatsapp.services.inbound import MENU_TEMPLATE_CODE, handle_inbound_message

    tenant, user, _template = wa_setup
    with use_tenant(tenant.id):
        menu = create_template(
            tenant,
            code=MENU_TEMPLATE_CODE,
            name="Menu",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="1. Suivi 2. Support 3. Humain",
            variables=[],
            estimated_cost_ariary=Decimal("20"),
        )
        submit_for_review(menu)
        approve_template(menu, user=user)

        monkeypatch.setattr(
            "apps.core.services.whatsapp.get_whatsapp_client", lambda: _FakeSucceedingClient()
        )
        handle_inbound_message(tenant, phone_number="+261340000009", body="bonjour")

        outbound = WhatsAppMessage.objects.filter(
            tenant_id=tenant.id,
            phone_number="+261340000009",
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        )
        assert outbound.count() == 1, "Le menu d'intentions ne laisse toujours aucune trace."
        row = outbound.first()
        assert row.template_name == MENU_TEMPLATE_CODE
        assert row.status == WhatsAppMessage.STATUS_SENT
        # Le coût est imputé (WA-4 « coût imputé », WA-5 : il pèse désormais
        # au plafond, ce qui n'était pas le cas).
        assert row.cost_ariary == Decimal("20")
        # `WaConversation` est protégée par RLS : la lire hors du contexte
        # tenant renverrait `DoesNotExist` quoi qu'ait fait le code testé.
        conversation = WaConversation.objects.get(phone_number="+261340000009")
        assert conversation.last_outbound_at is not None


# --- WA-10 : le routage par tenant, qui n'en était pas un ----------------------


def test_inbound_is_routed_to_the_tenant_owning_the_meta_number(wa_setup, settings) -> None:
    """**Ce que le lot précédent appelait « routage par tenant ».** Un
    `WHATSAPP_DEFAULT_TENANT_ID` unique pour tout le déploiement, et un
    webhook qui n'inspectait jamais le `phone_number_id` de l'entrée Meta :
    sur une instance multi-sociétés, les messages écrits par les clients de
    la société B tombaient dans le fil de la société A. C'est ce test qui
    manquait pour que l'énoncé soit vrai."""
    from django.test import Client as DjangoClient

    tenant_a, _user, _template = wa_setup
    tenant_b = Tenant.objects.create(code="L10-WA-B", name="Autre société")

    tenant_a.whatsapp_phone_number_id = "111111"
    tenant_a.save(update_fields=["whatsapp_phone_number_id"])
    tenant_b.whatsapp_phone_number_id = "222222"
    tenant_b.save(update_fields=["whatsapp_phone_number_id"])
    # Le tenant par defaut est A : sans routage reel, TOUT atterrirait chez A.
    settings.WHATSAPP_DEFAULT_TENANT_ID = str(tenant_a.id)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222"},
                            "messages": [
                                {
                                    "from": "+261340000077",
                                    "id": "wamid.b",
                                    "text": {"body": "bonjour B"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    response = DjangoClient().post(
        "/api/v1/whatsapp/webhook", data=payload, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json()["routed_by_phone_number_id"] == 1

    message = WhatsAppMessage.objects.get(provider_message_id="wamid.b")
    assert str(message.tenant_id) == str(tenant_b.id), (
        "Le message du numéro de la société B a été attribué à une autre société."
    )


def test_two_tenants_cannot_claim_the_same_meta_number(wa_setup) -> None:
    """Sans cette contrainte, le webhook choisirait en silence laquelle des
    deux sociétés reçoit les messages — un `.first()` sur un ordre non
    déterminé."""
    from django.db.utils import IntegrityError

    tenant_a, _user, _template = wa_setup
    tenant_a.whatsapp_phone_number_id = "333333"
    tenant_a.save(update_fields=["whatsapp_phone_number_id"])

    tenant_b = Tenant.objects.create(code="L10-WA-C", name="Troisième société")
    tenant_b.whatsapp_phone_number_id = "333333"
    with pytest.raises(IntegrityError):
        tenant_b.save(update_fields=["whatsapp_phone_number_id"])


def test_an_unclaimed_number_still_falls_back_to_the_default_tenant(wa_setup, settings) -> None:
    """Le repli historique est conservé : un déploiement mono-société n'a
    rien à router et ne doit pas se mettre à perdre ses messages entrants
    parce qu'un champ facultatif est vide."""
    from django.test import Client as DjangoClient

    tenant_a, _user, _template = wa_setup
    settings.WHATSAPP_DEFAULT_TENANT_ID = str(tenant_a.id)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "999999"},
                            "messages": [
                                {
                                    "from": "+261340000088",
                                    "id": "wamid.fallback",
                                    "text": {"body": "bonjour"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    response = DjangoClient().post(
        "/api/v1/whatsapp/webhook", data=payload, content_type="application/json"
    )
    assert response.status_code == 200
    # Le repli a joue, mais il est DIT : aucun routage reel n'a eu lieu.
    assert response.json()["routed_by_phone_number_id"] == 0

    message = WhatsAppMessage.objects.get(provider_message_id="wamid.fallback")
    assert str(message.tenant_id) == str(tenant_a.id)


def test_the_recipient_limit_is_settable_from_the_product(wa_setup) -> None:
    """Un plafond éditable seulement par `/admin/` n'est, en pratique,
    jamais réglé — c'est exactement ce qui était arrivé au régime fiscal
    avant L17."""
    from django.test import Client as DjangoClient

    from apps.core.tests.utils import grant_role

    tenant, user, _template = wa_setup
    with use_tenant(tenant.id):
        grant_role(user, "resp_commercial")
    client = DjangoClient()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        "/whatsapp/config/recipient-limit/", {"max_messages_per_recipient_per_day": "4"}
    )
    assert response.status_code in (200, 302)
    tenant.refresh_from_db()
    assert tenant.whatsapp_max_messages_per_recipient_per_day == 4
