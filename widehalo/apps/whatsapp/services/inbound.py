"""WA-6/WA-8 (cahier Phase 2 §13.4) : traitement gouverné d'un message
entrant — appelé par le webhook gouverné (`apps.whatsapp.api::
whatsapp_webhook_receive`), APRÈS la journalisation de base déjà assurée
par `apps.core.services.notifications.record_inbound_whatsapp_message`
(réutilisée telle quelle, jamais dupliquée)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.whatsapp.models import WaConversation
from apps.whatsapp.services.consent import get_or_create_conversation
from apps.whatsapp.services.templates import get_approved_template, render_body

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

# WA-8 : menu d'intentions BORNE — code du modèle APPROUVÉ attendu pour le
# relancer (cf. `services/templates.py::get_approved_template`) ; un tenant
# qui n'a pas encore approuvé ce modèle ne reçoit simplement AUCUNE relance
# automatique (dégradation silencieuse assumée, jamais un envoi non
# gouverné) — décision de conception disclosed.
MENU_TEMPLATE_CODE = "menu_principal"
# Choix reconnus dans la reponse du client — BORNE a 3 options fixes,
# jamais une comprehension de langage naturel ouverte.
_INTENT_CHOICE_SUPPORT = "1"
_INTENT_CHOICE_ORDER = "2"
_INTENT_CHOICE_HUMAN = "3"
_KNOWN_CHOICES = {_INTENT_CHOICE_SUPPORT, _INTENT_CHOICE_ORDER, _INTENT_CHOICE_HUMAN}

# WA-2 (L10) : mots-cles de DESABONNEMENT. Le consentement etait revocable
# depuis l'ecran interne uniquement : un client qui repondait « STOP » voyait
# son message classe en reponse inconnue, son consentement restait actif, et
# les campagnes continuaient de lui parvenir. Pire, l'operateur ne voyait
# meme pas le « STOP » — les messages entrants etaient enregistres sans
# tenant, donc invisibles de tous les ecrans (corrige au meme lot).
#
# Liste BORNEE et explicite, jamais une comprehension de langage naturel :
# meme discipline que le menu d'intentions ci-dessus. Les variantes retenues
# sont celles qu'un client francophone ou anglophone ecrit reellement.
# La comparaison est insensible a la casse et aux espaces, jamais a
# l'orthographe : « STOPPEZ » ou « je veux stopper » ne desabonnent PAS —
# un desabonnement decide sur une approximation serait aussi grave qu'un
# desabonnement manque.
UNSUBSCRIBE_KEYWORDS = frozenset(
    {"stop", "arret", "arrêt", "desabonnement", "désabonnement", "unsubscribe"}
)


def _open_chatter_channel(tenant: Tenant, conversation: WaConversation) -> None:
    """WA-6 : ouvre (ou reutilise) le canal chatter generique de la
    conversation — jamais un second mecanisme de messagerie interne. Aucun
    participant impose a l'ouverture (contrairement a `StgInitiative`, qui
    connait deja un responsable) : une conversation WhatsApp entrante n'a
    pas encore d'humain assigne, le canal reste rejoignable par n'importe
    quel collaborateur habilite depuis l'ecran de conversation."""
    if conversation.chat_channel_id:
        return
    from apps.chat.services.public import get_or_create_document_channel

    channel_id = get_or_create_document_channel(
        tenant=tenant,
        content_object=conversation,
        participants=[],
        title=f"WhatsApp — {conversation.phone_number}",
    )
    conversation.chat_channel_id = channel_id
    conversation.save(update_fields=["chat_channel_id", "updated_at"])


def _maybe_send_intent_menu(tenant: Tenant, conversation: WaConversation) -> None:
    """WA-8 : premiere prise de contact -> propose le menu borne.

    **Contournement assume et documente du point d'entree gouverne.** Une
    reponse au sein de la fenetre de service (WA-3) reste une reponse au
    client, jamais une sollicitation marketing : elle n'exige donc PAS le
    consentement WA-1/WA-2, qui protege les envois BUSINESS-initiated
    (cf. docstring `services/messaging.py`). C'est la seule voie du depot
    qui envoie hors de `send_governed_template_message`, et elle figure a
    ce titre dans la liste d'exception motivee de
    `tests/architecture/test_whatsapp_single_send_path.py`. Elle reste
    soumise a l'exigence de modele APPROUVE.

    **Ce que L10 corrige ici.** L'exemption portait sur le consentement ;
    elle avait ete etendue en pratique a la TRACABILITE, ce que rien ne
    justifiait. Ce message partait reellement au client sans creer aucune
    ligne `WhatsAppMessage` : invisible du journal des echanges (WA-4
    exige « envoi journalise avec modele, destinataire, statut, categorie
    et cout impute »), invisible de l'ecran de conversation, et compte pour
    zero au plafond de cout comme a la limite de frequence par
    destinataire (WA-5) — un client pouvait donc recevoir ce menu sans
    qu'aucun compteur ne le voie passer. Ne pas exiger un consentement
    n'est pas une raison de ne pas ecrire ce qu'on a envoye."""
    if conversation.intent_state != WaConversation.INTENT_NONE:
        return
    template = get_approved_template(tenant, MENU_TEMPLATE_CODE)
    if template is None:
        return
    from apps.core.models.notification import WhatsAppMessage
    from apps.core.services.whatsapp import get_whatsapp_client
    from apps.whatsapp.services.pricing import impute_cost

    result = get_whatsapp_client().send_template(
        conversation.phone_number, template.code, {"body": []}
    )
    # GRATUIT, et c'est une correction. L10 avait raison de rendre ce
    # message tracable — il partait reellement au client sans laisser de
    # ligne — mais il l'a fait passer d'un coup de « aucune trace » a
    # « trace + tarif plein », en sautant l'etape juste : une reponse
    # emise DANS la fenetre de service, a l'initiative du client, n'est
    # facturee sous AUCUN des deux regimes. Elle pesait donc au plafond
    # mensuel pour un montant que le tiers ne facture pas, et bloquait
    # d'autant les envois reels.
    #
    # Zero et non `None` : « gratuit » est un montant connu, « pas encore
    # impute » ne l'est pas. Meme distinction que sur `FlwExchange`.
    cout, unite = impute_cost(
        tenant, template=template, conversation_id=conversation.id, is_free_service_reply=True
    )
    WhatsAppMessage.objects.create(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        phone_number=conversation.phone_number,
        template_name=template.code,
        provider_message_id=result.provider_message_id,
        status=(
            WhatsAppMessage.STATUS_SENT
            if result.status == "sent"
            else WhatsAppMessage.STATUS_FAILED
        ),
        conversation_id=conversation.id,
        category=template.category,
        cost_ariary=cout,
        cost_unit=unite,
        body=render_body(template, {}),
    )
    conversation.intent_state = WaConversation.INTENT_MENU_SENT
    conversation.last_outbound_at = timezone.now()
    conversation.save(update_fields=["intent_state", "last_outbound_at", "updated_at"])


def _apply_intent_choice(conversation: WaConversation, body: str) -> None:
    choice = body.strip()
    if conversation.intent_state != WaConversation.INTENT_MENU_SENT or choice not in _KNOWN_CHOICES:
        return
    new_state = (
        WaConversation.INTENT_AWAITING_HUMAN
        if choice in (_INTENT_CHOICE_SUPPORT, _INTENT_CHOICE_HUMAN)
        else WaConversation.INTENT_RESOLVED
    )
    conversation.intent_state = new_state
    conversation.save(update_fields=["intent_state", "updated_at"])


def _is_unsubscribe(body: str) -> bool:
    return body.strip().casefold() in UNSUBSCRIBE_KEYWORDS


def handle_inbound_message(tenant: Tenant, *, phone_number: str, body: str) -> WaConversation:
    """Point d'entree gouverne pour un message entrant DEJA journalise
    (cf. docstring de module) — met a jour la conversation (WA-7 « etat
    visible »), traite un DESABONNEMENT (WA-2), ouvre le canal chatter
    (WA-6), et fait progresser le menu d'intentions borne (WA-8).

    **Le desabonnement passe avant tout le reste, et coupe court.** Un
    client qui ecrit « STOP » ne doit pas recevoir en retour un menu
    d'intentions : ce serait exactement le message qu'il vient de refuser.
    On revoque, on enregistre, et on s'arrete la — ni menu, ni relance."""
    conversation = get_or_create_conversation(tenant, phone_number)
    conversation.last_inbound_at = timezone.now()
    conversation.save(update_fields=["last_inbound_at", "updated_at"])

    if _is_unsubscribe(body):
        from apps.whatsapp.services.consent import revoke_consent

        conversation = revoke_consent(tenant, phone_number=phone_number)
        # Le canal chatter reste ouvert : un desabonnement est une
        # information que l'equipe doit voir, pas un effacement.
        _open_chatter_channel(tenant, conversation)
        return conversation

    _open_chatter_channel(tenant, conversation)
    _apply_intent_choice(conversation, body)
    _maybe_send_intent_menu(tenant, conversation)
    return conversation


__all__ = ["MENU_TEMPLATE_CODE", "handle_inbound_message"]
