"""H26 — l'unité de coût, et les deux sur-comptages qu'elle a fait voir.

L'hypothèse H26 du cahier posait une question binaire : le compteur
existant encaisse-t-il une bascule vers la facturation au message sans
reprise d'historique ? La réponse est « à moitié », et c'est ce demi-vrai
qui était dangereux. Le coût est figé sur la ligne à l'envoi — l'historique
est donc immunisé, ce qui est la moitié favorable. Mais rien
n'enregistrait sous quelle unité, si bien qu'un total à cheval sur une
bascule aurait été exact à l'ariary et pourtant incomparable à la période
précédente, sans que rien ne le signale.

Plutôt que de parier sur une branche, l'unité devient une donnée. Ces
tests vérifient que les deux régimes produisent des imputations
différentes — sans quoi le champ serait une étiquette décorative — et que
la bascule s'exprime par un paramètre versionné, donc par une date.

Deux défauts réels ont été trouvés en instruisant l'hypothèse, et sont
vérifiés ici : la réponse en fenêtre de service était facturée alors
qu'elle est gratuite sous les deux régimes, et un message refusé par la
gouvernance gardait un coût imputé qu'il n'aurait jamais engagé.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.cost_units import (
    COST_UNIT_CONVERSATION,
    COST_UNIT_MESSAGE,
    COST_UNIT_PARAMETER_CODE,
    DEFAULT_COST_UNIT,
    cost_unit_in_force,
)
from apps.core.models.notification import WhatsAppMessage
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.pricing import impute_cost, window_already_billed

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="H26", name="Coût messagerie SARL")
    with use_tenant(tenant.id):
        template = WaMessageTemplate.objects.create(
            tenant=tenant,
            code="rappel_facture",
            name="Rappel de facture",
            category=WaMessageTemplate.CATEGORY_UTILITY,
            body_text="Bonjour",
            estimated_cost_ariary=Decimal("50"),
            status=WaMessageTemplate.STATUS_APPROVED,
        )
        conversation = WaConversation.objects.create(tenant=tenant, phone_number="+261340000001")
    return tenant, template, conversation


def _set_unit(unit: str, *, valid_from: dt.date) -> None:
    RegulatoryParameter.objects.create(
        tenant=None, code=COST_UNIT_PARAMETER_CODE, value=unit, valid_from=valid_from
    )


# --- L'unité est une donnée, pas une constante -------------------------------


def test_the_unit_in_force_falls_back_without_blocking_anything() -> None:
    """Un compteur qui lèverait faute de paramètre bloquerait l'envoi de
    messages pour un motif de configuration — la même faute que le
    référentiel de TVA absent empêchant de construire un socle de
    simulation, corrigée en L17."""
    RegulatoryParameter.objects.filter(code=COST_UNIT_PARAMETER_CODE).delete()
    assert cost_unit_in_force(at_date=dt.date(2026, 6, 1)) == DEFAULT_COST_UNIT


def test_the_seeded_default_is_what_the_counter_already_did() -> None:
    """Semer « conversation » aurait changé en silence le comportement de
    tous les déploiements existants — exactement le défaut qu'une bascule
    non datée produit. Le paramètre semé dit ce que le code FAISAIT."""
    assert cost_unit_in_force(at_date=dt.date(2026, 6, 1)) == COST_UNIT_MESSAGE


def test_a_switch_is_a_date_not_a_deployment() -> None:
    """Le repli de H26 demande « deux unités qui coexistent, avec une date
    de bascule ». Le mécanisme existait déjà dans ce dépôt sans être
    employé : la table de paramètres est versionnée par plage de validité,
    donc une bascule est une ligne de plus."""
    ancienne = RegulatoryParameter.objects.get(code=COST_UNIT_PARAMETER_CODE, tenant__isnull=True)
    ancienne.valid_to = dt.date(2026, 6, 30)
    ancienne.save(update_fields=["valid_to"])
    _set_unit(COST_UNIT_CONVERSATION, valid_from=dt.date(2026, 7, 1))

    assert cost_unit_in_force(at_date=dt.date(2026, 6, 15)) == COST_UNIT_MESSAGE
    assert cost_unit_in_force(at_date=dt.date(2026, 7, 15)) == COST_UNIT_CONVERSATION


def test_an_unknown_unit_does_not_silently_change_the_regime() -> None:
    """Un paramètre mal saisi ne doit pas faire basculer toute la
    facturation d'un tenant vers une unité que le code ne sait pas
    totaliser. Repli sur l'unité connue, et un avertissement."""
    RegulatoryParameter.objects.filter(code=COST_UNIT_PARAMETER_CODE).delete()
    _set_unit("au_kilo", valid_from=dt.date(2026, 1, 1))
    assert cost_unit_in_force(at_date=dt.date(2026, 6, 1)) == DEFAULT_COST_UNIT


# --- Les deux régimes n'imputent pas la même chose ----------------------------


def test_per_message_charges_every_message(setup) -> None:
    tenant, template, conversation = setup
    with use_tenant(tenant.id):
        for _ in range(3):
            cout, unite = impute_cost(tenant, template=template, conversation_id=conversation.id)
            assert cout == Decimal("50")
            assert unite == COST_UNIT_MESSAGE
            WhatsAppMessage.objects.create(
                tenant_id=tenant.id,
                direction=WhatsAppMessage.DIRECTION_OUTBOUND,
                phone_number=conversation.phone_number,
                conversation_id=conversation.id,
                category=template.category,
                cost_ariary=cout,
                cost_unit=unite,
            )


def test_per_conversation_charges_the_window_once(setup) -> None:
    """Le cœur de la bascule. Sous facturation à la conversation, une
    fenêtre de 24 h par catégorie est facturée une fois quel que soit le
    nombre de messages — et c'est ce que le compteur ne savait pas faire.

    Si ce test passait avec la même imputation que le précédent, l'unité
    serait une étiquette décorative."""
    tenant, template, conversation = setup
    RegulatoryParameter.objects.filter(code=COST_UNIT_PARAMETER_CODE).delete()
    _set_unit(COST_UNIT_CONVERSATION, valid_from=dt.date(2026, 1, 1))

    with use_tenant(tenant.id):
        couts = []
        for _ in range(3):
            cout, unite = impute_cost(tenant, template=template, conversation_id=conversation.id)
            assert unite == COST_UNIT_CONVERSATION
            couts.append(cout)
            WhatsAppMessage.objects.create(
                tenant_id=tenant.id,
                direction=WhatsAppMessage.DIRECTION_OUTBOUND,
                phone_number=conversation.phone_number,
                conversation_id=conversation.id,
                category=template.category,
                cost_ariary=cout,
                cost_unit=unite,
            )

    assert couts == [Decimal("50"), Decimal(0), Decimal(0)], (
        f"Imputations {couts} : la fenêtre est facturée plus d'une fois, ou l'unité "
        "ne change rien à l'imputation."
    )


def test_two_categories_are_two_billable_windows(setup) -> None:
    """Meta facture par catégorie : une fenêtre utilitaire et une fenêtre
    marketing sur le même numéro sont deux conversations facturables.
    Regrouper sur la seule conversation sous-facturerait."""
    tenant, template, conversation = setup
    RegulatoryParameter.objects.filter(code=COST_UNIT_PARAMETER_CODE).delete()
    _set_unit(COST_UNIT_CONVERSATION, valid_from=dt.date(2026, 1, 1))

    with use_tenant(tenant.id):
        marketing = WaMessageTemplate.objects.create(
            tenant=tenant,
            code="promo",
            name="Promotion",
            category=WaMessageTemplate.CATEGORY_MARKETING,
            body_text="Offre",
            estimated_cost_ariary=Decimal("80"),
            status=WaMessageTemplate.STATUS_APPROVED,
        )
        cout_utile, _u = impute_cost(tenant, template=template, conversation_id=conversation.id)
        WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number=conversation.phone_number,
            conversation_id=conversation.id,
            category=template.category,
            cost_ariary=cout_utile,
        )
        cout_marketing, _u = impute_cost(
            tenant, template=marketing, conversation_id=conversation.id
        )

    assert cout_utile == Decimal("50")
    assert cout_marketing == Decimal("80"), (
        "La fenêtre marketing a été portée par la fenêtre utilitaire : les deux "
        "catégories sont facturées séparément par le fournisseur."
    )


def test_the_billing_window_expires(setup) -> None:
    """Vingt-cinq heures plus tard, la fenêtre est close et une nouvelle
    est facturée. Sans expiration, une conversation ouverte une fois serait
    gratuite pour toujours."""
    tenant, template, conversation = setup
    with use_tenant(tenant.id):
        WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number=conversation.phone_number,
            conversation_id=conversation.id,
            category=template.category,
            cost_ariary=Decimal("50"),
        )
        maintenant = timezone.now()
        assert window_already_billed(
            tenant,
            conversation_id=conversation.id,
            category=template.category,
            now=maintenant,
        )
        assert not window_already_billed(
            tenant,
            conversation_id=conversation.id,
            category=template.category,
            now=maintenant + dt.timedelta(hours=25),
        )


def test_conversation_id_finally_has_a_reader(setup) -> None:
    """Le champ était écrit par les trois écrivains de `WhatsAppMessage` et
    lu par personne — le seul lecteur du dépôt était un test vérifiant
    qu'il n'était pas nul. C'est le motif que ce projet corrige depuis le
    début : une donnée correcte que rien n'interroge. Il est désormais la
    clef de la fenêtre de facturation, et ce test le prouve en montrant
    qu'une AUTRE conversation ne porte pas la fenêtre de celle-ci."""
    tenant, template, conversation = setup
    with use_tenant(tenant.id):
        autre = WaConversation.objects.create(tenant=tenant, phone_number="+261340000002")
        WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number=conversation.phone_number,
            conversation_id=conversation.id,
            category=template.category,
            cost_ariary=Decimal("50"),
        )
        assert window_already_billed(
            tenant, conversation_id=conversation.id, category=template.category
        )
        assert not window_already_billed(
            tenant, conversation_id=autre.id, category=template.category
        )


# --- Les deux sur-comptages, corrigés -----------------------------------------


def test_a_service_window_reply_costs_nothing(setup) -> None:
    """Une réponse émise dans la fenêtre de service, à l'initiative du
    client, n'est facturée sous AUCUN des deux régimes. Elle l'était.

    Zéro et non `None` : « gratuit » est un montant connu."""
    tenant, template, conversation = setup
    with use_tenant(tenant.id):
        cout, unite = impute_cost(
            tenant,
            template=template,
            conversation_id=conversation.id,
            is_free_service_reply=True,
        )
    assert cout == Decimal(0)
    assert unite != "", "Un coût gratuit reste un coût imputé : il porte son unité."


def test_a_governance_refusal_stops_weighing_on_the_cap(setup) -> None:
    """Un message refusé par la gouvernance n'est jamais parti et ne
    partira jamais — un refus de consentement ne passera pas avec le
    temps, il n'entre pas dans le cycle de reprise. Lui laisser son coût
    imputé fait peser au plafond mensuel un montant que le fournisseur ne
    facturera jamais, et bloque d'autant des envois réels.

    La ligne garde sa trace ; c'est `error_message` qui dit pourquoi elle
    vaut zéro."""
    from apps.core.tests.factories import UserFactory
    from apps.whatsapp.services.consent import grant_consent, revoke_consent
    from apps.whatsapp.services.messaging import (
        flush_pending_messages,
        queue_governed_template_message,
    )

    tenant, template, conversation = setup
    with use_tenant(tenant.id):
        utilisateur = UserFactory()
        grant_consent(tenant, phone_number=conversation.phone_number, source="test")
        message = queue_governed_template_message(
            tenant,
            phone_number=conversation.phone_number,
            template_code=template.code,
            variables={},
            user=utilisateur,
        )
        assert message.cost_ariary == Decimal("50")

        # Le consentement est retiré ENTRE la mise en file et l'envoi —
        # c'est le cas que la double vérification de L10 existe pour
        # attraper.
        revoke_consent(tenant, phone_number=conversation.phone_number)
        flush_pending_messages(tenant)

        message.refresh_from_db()
        assert message.status == WhatsAppMessage.STATUS_FAILED
        assert message.error_message != ""
        assert message.cost_ariary == Decimal(0), (
            "Un message refusé par la gouvernance pèse encore au plafond : le total "
            "mensuel compte un envoi qui n'a jamais eu lieu."
        )


def test_the_alert_threshold_finally_has_a_reader(setup) -> None:
    """`is_alert_threshold_exceeded` existait, était testée, et n'avait
    aucun appelant de production — pendant que
    `whatsapp_cost_alert_threshold_pct` était un champ réglable qui ne
    déclenchait rien. Un seuil qu'on peut saisir et qui ne fait rien est
    pire qu'un seuil absent : il donne le sentiment d'être protégé.

    « Alerte à l'approche, pas seulement à l'atteinte » (cahier §10.2) :
    « un plafond atteint un 28 du mois sans avertissement est vécu comme
    une panne »."""
    import inspect

    from apps.whatsapp import views

    source = inspect.getsource(views)
    assert "is_alert_threshold_exceeded(" in source, (
        "La fonction d'alerte n'a de nouveau aucun appelant de production : le seuil "
        "réglable ne déclenche plus rien."
    )
