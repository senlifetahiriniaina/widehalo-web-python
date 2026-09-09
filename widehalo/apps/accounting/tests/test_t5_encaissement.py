"""T5 — la chaîne d'encaissement, parcourue en entier et par le vrai bus.

**Pourquoi ce fichier existe, et ce qu'aucun autre ne pouvait dire.** Les
maillons de T5 sont vérifiés isolément : le webhook refuse ce qu'il doit
refuser (`flows/tests/test_t5_webhook.py`), la corrélation n'écrit que sur
référence retrouvée, la commission s'isole sur son compte. Chacun passe.
Cela ne dit rien de la CHAÎNE — et c'est précisément ce que le cahier
demande de vérifier : « chaque étape traçable par une seule clé de
corrélation » (l.1053).

**Rien n'est simulé ici, et c'est la seule façon que le test vaille
quelque chose.** Le corps est réellement signé, réellement posté sur
l'URL publique, l'échange entrant est réellement écrit, l'événement
réellement publié, et l'abonné réellement appelé PAR LE BUS — le réglage
`sync` des tests exécute Django-Q en ligne, et `transaction=True` fait
tourner les rappels `on_commit`. Appeler `receive_payment_notification` à
la main aurait vérifié une fonction, pas un chemin : c'est exactement
ainsi qu'on livre six maillons corrects qui ne se touchent pas.

**Ce que le premier passage a trouvé.** L'échange ENTRANT naissait sans
clef de corrélation — `assign_keys` ne la pose qu'à la mise en file,
c'est-à-dire sur le seul chemin sortant. `lineage()` rendait donc la
soumission et ses réessais, et jamais la notification qui les a tranchés :
la seule des trois qui dise ce que la facture est DEVENUE. Le test le plus
important de ce fichier est celui qui compte les échanges d'une même
lignée.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone

from apps.accounting.models import (
    AccAccount,
    AccAggregatorPayout,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPaymentIntent,
    AccPaymentNotification,
    AccPeriod,
    AccTenantDefaultAccount,
)
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.accounting.services.payment_intents import (
    REEMIT_NOTIFIED,
    REEMIT_SETTLED,
    REEMIT_STILL_PAYABLE,
    create_payment_intent,
    reemit_intent,
)
from apps.accounting.services.payment_payouts import (
    OUTCOME_MISMATCH,
    announce_payout,
    settle_payout,
)
from apps.accounting.services.payment_providers import PROVIDER_AGGREGATOR
from apps.accounting.services.payment_registration import CONNECTOR_CODE
from apps.accounting.services.payments import outstanding_balance
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwCredential, FlwExchange, FlwLink
from apps.flows.operations import OP_INITIATE_PAYMENT, OP_RECEIVE_EVENT
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

# `transaction=True` n'est pas un detail de confort : `publish_event`
# programme la distribution sur `on_commit`, et pytest-django n'execute
# jamais ces rappels dans une transaction qu'il annule. Sans lui, le
# webhook rendrait 200, l'echange serait ecrit, et l'abonne ne serait
# JAMAIS appele — un test vert qui ne prouve rien.
pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "secret-de-webhook-encaissement"  # noqa: S105 - valeur de test, jamais un secret reel.

#: Ce que le client doit, et ce qu'il paie : le BRUT. C'est lui qui éteint
#: la créance — encaisser le net laisserait 20 de créance ouverte sur un
#: client qui ne doit plus rien, et la relance irait les lui réclamer.
MONTANT_FACTURE = Decimal("1000")
#: Ce que l'agrégateur retient. Isolée sur son compte de charge (PAY-5),
#: et retenue SUR SON VERSEMENT — pas sur chaque transaction.
COMMISSION = Decimal("20")
#: Ce qui arrive réellement en banque, le jour du versement groupé.
MONTANT_VERSE = MONTANT_FACTURE - COMMISSION


def _grant(user: User, group_name: str, *codenames: str) -> None:
    group, _ = Group.objects.get_or_create(name=group_name)
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="accounting")
        group.permissions.add(permission)
    user.groups.add(group)


@pytest.fixture
def societe():
    """Une société qui encaisse par agrégateur, avec son raccordement ouvert.

    Le plan comptable est le minimum qui rende l'écriture possible : une
    créance, un produit, une banque, un écart, et — c'est le point du
    critère PAY-5 — un compte de charge DISTINCT pour la commission."""
    tenant = Tenant.objects.create(
        code="T5-E2E",
        name="Encaissement de bout en bout",
        # PAY-1 : le choix de la voie est un PARAMETRE, jamais du code.
        mobile_payment_provider=PROVIDER_AGGREGATOR,
    )
    with use_tenant(tenant.id):
        exercice = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        periode = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=exercice,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal_ventes = AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        journal_banque = AccJournal.objects.create(
            tenant=tenant,
            code="BQ",
            name="Banque",
            type=AccJournal.TYPE_BANK,
            sequence_prefix="BQ",
        )
        creance = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        produit = AccAccount.objects.create(
            tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        banque = AccAccount.objects.create(
            tenant=tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        ecart = AccAccount.objects.create(
            tenant=tenant,
            code="658",
            name="Ecart de caisse",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        commission = AccAccount.objects.create(
            tenant=tenant,
            code="627",
            name="Commissions d'encaissement",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        # Le compte de PASSAGE : ce que l'agrégateur nous doit entre
        # l'encaissement et son versement. Sans lui, l'encaissement
        # débiterait la banque d'un argent qui n'y est pas, et le
        # versement groupé n'aurait plus rien à solder.
        passage = AccAccount.objects.create(
            tenant=tenant,
            code="471",
            name="Encaissements en attente de versement",
            account_class=4,
            type=AccAccount.TYPE_ASSET,
        )
        # Renseignes explicitement plutot que laisses au repli par TYPE :
        # deux comptes de charge existent ici, et un repli qui choisirait
        # « une charge » ferait passer la commission pour un ecart de
        # caisse — soit exactement le defaut que PAY-5 interdit.
        for role, compte in (
            (AccTenantDefaultAccount.ROLE_BANK, banque),
            (AccTenantDefaultAccount.ROLE_CASH_DIFFERENCE, ecart),
            (AccTenantDefaultAccount.ROLE_PAYMENT_FEE, commission),
            (AccTenantDefaultAccount.ROLE_PAYMENT_CLEARING, passage),
        ):
            AccTenantDefaultAccount.objects.create(tenant=tenant, role=role, account=compte)

        comptable = User.objects.create_user(
            email="comptable-t5@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(comptable, "comptable", "validate_accmove")
        ensure_default_approval_thresholds(tenant)

        connecteur = FlwConnectorFactory(tenant=tenant, code=CONNECTOR_CODE)
        liaison = FlwLinkFactory(tenant=tenant, connector=connecteur, state=FlwLink.STATE_ACTIVE)
        FlwCredential.objects.create(
            tenant=tenant,
            connector=connecteur,
            label="Secret de webhook",
            kind=FlwCredential.KIND_WEBHOOK_SECRET,
            secret=SECRET,
        )

    return {
        "tenant": tenant,
        "periode": periode,
        "journal_ventes": journal_ventes,
        "journal_banque": journal_banque,
        "creance": creance,
        "produit": produit,
        "banque": banque,
        "ecart": ecart,
        "commission": commission,
        "passage": passage,
        "comptable": comptable,
        "liaison": liaison,
    }


def _facture_validee(ctx, montant: Decimal = MONTANT_FACTURE) -> AccMove:
    facture = create_invoice(
        tenant=ctx["tenant"],
        journal=ctx["journal_ventes"],
        period=ctx["periode"],
        date=dt.date(2026, 1, 15),
        partner_id=None,
        receivable_account=ctx["creance"],
        income_lines=[{"account": ctx["produit"], "amount": montant, "label": "Vente"}],
        currency="MGA",
    )
    return validate_invoice(facture, ctx["comptable"])


def _solde_debiteur(compte: AccAccount) -> Decimal:
    """Débits moins crédits sur un compte, toutes pièces publiées confondues.

    Le solde plutôt que la somme des débits : une écriture qui débite puis
    crédite le même compte n'y laisse rien, et c'est exactement ce qu'on
    veut mesurer sur le compte de passage."""
    lignes = AccMoveLine.objects.filter(account=compte, move__state=AccMove.STATE_POSTED)
    return sum((ligne.debit - ligne.credit for ligne in lignes), Decimal(0))


def _du(facture: AccMove) -> Decimal:
    """Ce qui reste dû sur la facture, lu sur sa ligne de créance.

    `outstanding_balance` prend une LIGNE, jamais une pièce — c'est la ligne
    de créance qui porte le solde, et une facture peut en porter plusieurs.
    Le raccourci est ici, une seule fois, pour que les tests parlent de ce
    qu'ils vérifient et pas de la structure du grand livre."""
    facture.refresh_from_db()
    return outstanding_balance(facture.lines.filter(debit__gt=0).first())


def _notifier(
    ctx,
    *,
    reference: str,
    montant: Decimal = MONTANT_FACTURE,
    commission: Decimal = COMMISSION,
    marqueur: str = "",
    signature: str | None = None,
):
    """Signe et poste une notification d'opérateur, comme le ferait le tiers.

    `marqueur` ne sert qu'à faire varier l'empreinte du corps : la
    protection anti-rejeu du hub refuse deux fois le MÊME corps, ce qui est
    son travail. Pour vérifier la déduplication COMPTABLE (PAY-4), il faut
    deux corps distincts portant la même référence — c'est ce qu'un
    opérateur envoie quand il renvoie un événement enrichi."""
    corps = json.dumps(
        {
            "reference": reference,
            "amount": str(montant),
            "fee": str(commission),
            "provider": PROVIDER_AGGREGATOR,
            "currency": "MGA",
            **({"note": marqueur} if marqueur else {}),
        },
        sort_keys=True,
    ).encode("utf-8")
    horodatage = str(int(timezone.now().timestamp()))
    if signature is None:
        signature = hmac.new(
            SECRET.encode("utf-8"),
            horodatage.encode("utf-8") + b"." + corps,
            hashlib.sha256,
        ).hexdigest()
    return Client().post(
        f"/api/v1/flows/webhooks/{ctx['liaison'].id}",
        data=corps,
        content_type="application/json",
        HTTP_X_SIGNATURE=signature,
        HTTP_X_TIMESTAMP=horodatage,
    )


# --- Le chemin nominal, de bout en bout ---------------------------------------


def test_the_whole_chain_produces_the_entry_without_an_accountant(societe) -> None:
    """**LE critère PAY-2**, et il se lit d'un bout à l'autre.

    Facture validée -> intention émise -> notification signée reçue par le
    webhook -> écriture produite. Aucun humain n'intervient entre la
    signature du tiers et l'écriture, et c'est ce que le cahier autorise :
    la corrélation n'est pas une devinette, c'est une référence que nous
    avons nous-mêmes émise."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        assert intention.external_reference, (
            "Une intention sans référence ne peut corréler avec rien : c'est la "
            "clef que nous transmettons au payeur et que l'opérateur nous renvoie."
        )
        du_avant = _du(facture)

    reponse = _notifier(societe, reference=intention.external_reference)
    assert reponse.status_code == 200

    with use_tenant(societe["tenant"].id):
        notification = AccPaymentNotification.objects.get(
            external_reference=intention.external_reference
        )
        assert notification.state == AccPaymentNotification.STATE_MATCHED
        assert notification.payment_id is not None, (
            "Rapprochée sans paiement : la notification aurait été corrélée sans "
            "que l'écriture soit produite, et PAY-2 ne serait tenu qu'à moitié."
        )
        assert _du(facture) == du_avant - MONTANT_FACTURE

        intention.refresh_from_db()
        assert intention.state == AccPaymentIntent.STATE_SETTLED


def test_an_aggregator_payment_waits_in_the_clearing_account(societe) -> None:
    """**Ce qui rend PAY-5 possible, et que rien ne faisait.** Un agrégateur
    encaisse POUR NOUS ; l'argent n'est pas en banque tant qu'il n'a pas
    versé. Le porter en banque à la notification y ferait apparaître un
    argent absent — et surtout, le versement groupé n'aurait plus aucune
    contrepartie à solder."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )

    _notifier(societe, reference=intention.external_reference)

    with use_tenant(societe["tenant"].id):
        assert _solde_debiteur(societe["passage"]) == MONTANT_FACTURE, (
            "L'encaissement d'un agrégateur doit attendre au compte de passage."
        )
        assert _solde_debiteur(societe["banque"]) == Decimal(0), (
            "La banque a été débitée d'un argent que l'agrégateur n'a pas encore versé."
        )
        assert _solde_debiteur(societe["commission"]) == Decimal(0), (
            "La commission a été écrite à l'encaissement ALORS QU'ELLE EST RETENUE "
            "SUR LE VERSEMENT : elle sera comptée deux fois, et le compte de "
            "passage ne se soldera jamais."
        )


def test_the_payout_settles_the_batch_and_isolates_the_commission(societe) -> None:
    """**LE critère PAY-5**, en entier : « le versement groupé de
    l'agrégateur est rapproché du lot d'encaissements qu'il couvre, la
    commission étant isolée sur son propre compte de charge »."""
    with use_tenant(societe["tenant"].id):
        references = []
        for _rang in range(2):
            facture = _facture_validee(societe)
            intention = create_payment_intent(
                societe["tenant"],
                document_type="accounting.AccMove",
                document_id=facture.id,
                amount=MONTANT_FACTURE,
            )
            references.append(intention.external_reference)

    for reference in references:
        assert _notifier(societe, reference=reference).status_code == 200

    brut = MONTANT_FACTURE * 2
    with use_tenant(societe["tenant"].id):
        versement = announce_payout(
            societe["tenant"],
            provider_code=PROVIDER_AGGREGATOR,
            external_reference="PAYOUT-001",
            payout_date=dt.date(2026, 1, 31),
            gross_amount=brut,
            fee_amount=COMMISSION,
            net_amount=brut - COMMISSION,
        )
        resultat = settle_payout(versement)

    assert resultat.produced_an_entry, f"Versement non rapproché : {resultat.outcome}"

    with use_tenant(societe["tenant"].id):
        assert _solde_debiteur(societe["banque"]) == brut - COMMISSION
        assert _solde_debiteur(societe["commission"]) == COMMISSION, (
            "La commission n'est pas isolée sur son propre compte de charge."
        )
        assert _solde_debiteur(societe["passage"]) == Decimal(0), (
            "Le compte de passage n'est pas soldé : l'agrégateur nous devrait "
            "encore de l'argent qu'il a pourtant versé."
        )


def test_the_batch_and_the_payout_share_one_matching_number(societe) -> None:
    """« Rapproché du lot » cesse d'être une figure de style quand les N
    encaissements et le versement portent LE MÊME numéro de lettrage.

    Un numéro par pièce produirait N rapprochements de deux lignes,
    c'est-à-dire aucun rapprochement de lot — et le compte de passage
    resterait illisible, ce qui est exactement l'état d'avant."""
    with use_tenant(societe["tenant"].id):
        references = []
        for _rang in range(2):
            facture = _facture_validee(societe)
            intention = create_payment_intent(
                societe["tenant"],
                document_type="accounting.AccMove",
                document_id=facture.id,
                amount=MONTANT_FACTURE,
            )
            references.append(intention.external_reference)

    for reference in references:
        _notifier(societe, reference=reference)

    brut = MONTANT_FACTURE * 2
    with use_tenant(societe["tenant"].id):
        versement = announce_payout(
            societe["tenant"],
            provider_code=PROVIDER_AGGREGATOR,
            external_reference="PAYOUT-002",
            payout_date=dt.date(2026, 1, 31),
            gross_amount=brut,
            fee_amount=COMMISSION,
            net_amount=brut - COMMISSION,
        )
        settle_payout(versement)

        numeros = set(
            AccMoveLine.objects.filter(account=societe["passage"])
            .exclude(matching_number="")
            .values_list("matching_number", flat=True)
        )
        lignes_lettrees = AccMoveLine.objects.filter(
            account=societe["passage"], matching_number__in=numeros
        ).count()

    assert len(numeros) == 1, (
        f"{len(numeros)} numéros de lettrage sur le compte de passage ; il en "
        "faut UN seul, partagé par le lot et son versement."
    )
    assert lignes_lettrees == 3, (
        "Le lettrage doit porter sur les DEUX encaissements et le versement "
        f"(3 lignes) ; il en couvre {lignes_lettrees}."
    )


def test_a_payout_that_does_not_add_up_writes_nothing(societe) -> None:
    """Même discipline que la notification orpheline (PAY-3) : ce qui ne
    tombe pas juste ne s'écrit pas.

    Forcer l'équilibre en logeant la différence dans un compte d'écart
    ferait disparaître, dans une écriture de régularisation, précisément le
    fait qu'un agrégateur ne verse pas ce qu'il doit."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )

    _notifier(societe, reference=intention.external_reference)

    with use_tenant(societe["tenant"].id):
        versement = announce_payout(
            societe["tenant"],
            provider_code=PROVIDER_AGGREGATOR,
            external_reference="PAYOUT-FAUX",
            payout_date=dt.date(2026, 1, 31),
            # Annonce un brut qui ne correspond pas au lot encaissé.
            gross_amount=MONTANT_FACTURE * 5,
            fee_amount=COMMISSION,
            net_amount=MONTANT_FACTURE * 5 - COMMISSION,
        )
        resultat = settle_payout(versement)

        assert not resultat.produced_an_entry
        assert resultat.outcome == OUTCOME_MISMATCH
        versement.refresh_from_db()
        assert versement.state == AccAggregatorPayout.STATE_DISPUTED
        assert versement.move_id is None
        assert _solde_debiteur(societe["banque"]) == Decimal(0)
        assert _solde_debiteur(societe["passage"]) == MONTANT_FACTURE


def test_one_single_correlation_key_links_every_step(societe) -> None:
    """**La propriété que le cahier demande nommément** (l.1053) : « chaque
    étape traçable par une seule clé de corrélation ».

    L'émission de l'intention est un échange SORTANT ; la notification est
    un échange ENTRANT. Les deux doivent porter la MÊME clef, et cette clef
    doit désigner la facture — sinon « qu'est devenue cette facture ? »
    rend la demande partie et jamais la réponse reçue."""
    from apps.flows.services.idempotency import lineage
    from apps.flows.services.public import list_exchanges_for_document

    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )

    _notifier(societe, reference=intention.external_reference)

    attendue = f"accounting.AccMove:{facture.id}"
    with use_tenant(societe["tenant"].id):
        lignee = lineage(societe["tenant"].id, attendue)
        operations = {(echange.direction, echange.operation) for echange in lignee}
        # Tous les echanges qui touchent CETTE facture, lignee comprise ou
        # non. C'est la mesure qui compte : comparer la lignee a elle-meme
        # ne dirait rien, puisque `lineage()` filtre deja sur la clef.
        tous = list_exchanges_for_document(
            societe["tenant"], document_type="accounting.AccMove", document_id=facture.id
        )

    assert (FlwExchange.DIRECTION_OUTBOUND, OP_INITIATE_PAYMENT) in operations, (
        "L'émission de l'intention n'est pas dans la lignée de la facture."
    )
    assert (FlwExchange.DIRECTION_INBOUND, OP_RECEIVE_EVENT) in operations, (
        "La notification entrante n'est pas dans la lignée de la facture : "
        "`lineage()` rendrait la demande partie et jamais la réponse reçue, "
        "c'est-à-dire tout sauf ce que la facture est DEVENUE."
    )
    assert {echange["correlation_key"] for echange in tous} == {attendue}, (
        "Un echange rattache a cette facture porte une autre clef (ou aucune) : "
        "il existe alors deux histoires pour une seule piece, et « qu'est "
        "devenue cette facture ? » n'en rendrait qu'une."
    )
    assert len(tous) == len(lignee)


# --- Ce que la chaîne refuse de faire -----------------------------------------


def test_a_badly_signed_notification_produces_nothing_at_all(societe) -> None:
    """**API-3 vu depuis la comptabilité.** Le webhook refuse — c'est déjà
    vérifié côté hub — mais ce qui compte ici est qu'AUCUNE écriture n'ait
    été produite : un refus qui laisserait passer l'effet métier ne serait
    pas un refus."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        du_avant = _du(facture)

    reponse = _notifier(societe, reference=intention.external_reference, signature="00" * 32)
    assert reponse.status_code == 403

    with use_tenant(societe["tenant"].id):
        assert not AccPaymentNotification.objects.exists()
        assert _du(facture) == du_avant
        intention.refresh_from_db()
        assert intention.state != AccPaymentIntent.STATE_SETTLED


def test_an_unknown_reference_is_kept_orphan_and_writes_nothing(societe) -> None:
    """**PAY-3** : « un paiement reçu sans correspondance est placé en
    attente de rapprochement […] et ne produit aucune écriture tant qu'il
    n'est pas affecté ». La notification est authentique — elle est signée —
    et elle ne corrèle avec rien : elle se voit, elle n'écrit pas.

    **Une intention EXISTE par ailleurs**, et c'est ce qui donne sa force
    au test : sans elle, la corrélation n'aurait rien à trouver et le test
    passerait même si le code se contentait de prendre la première
    intention venue. Le cas réel est celui-là — une société qui encaisse a
    toujours des demandes en cours quand un payeur se trompe de
    référence."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        autre = _facture_validee(societe)
        create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=autre.id,
            amount=MONTANT_FACTURE,
        )
        du_avant = _du(facture)

    reponse = _notifier(societe, reference="WH-REFERENCE-QUE-NOUS-N-AVONS-JAMAIS-EMISE")
    assert reponse.status_code == 200

    with use_tenant(societe["tenant"].id):
        notification = AccPaymentNotification.objects.get()
        assert notification.state == AccPaymentNotification.STATE_ORPHAN
        assert notification.payment_id is None
        assert _du(facture) == du_avant
        assert not AccPayment.objects.exists()


def test_the_same_payment_notified_twice_settles_once(societe) -> None:
    """**PAY-4** : « une double notification du même paiement produit un
    seul encaissement et une seule écriture ».

    Les deux corps diffèrent d'un champ de commodité — sans quoi c'est
    l'anti-rejeu du hub qui refuserait, et la déduplication COMPTABLE ne
    serait jamais atteinte. C'est le cas réel : un opérateur qui renvoie un
    événement enrichi renvoie le même paiement sous une forme différente."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        du_avant = _du(facture)

    assert _notifier(societe, reference=intention.external_reference).status_code == 200
    assert (
        _notifier(societe, reference=intention.external_reference, marqueur="renvoi").status_code
        == 200
    )

    with use_tenant(societe["tenant"].id):
        etats = sorted(
            AccPaymentNotification.objects.filter(
                external_reference=intention.external_reference
            ).values_list("state", flat=True)
        )
        assert etats == sorted(
            [AccPaymentNotification.STATE_MATCHED, AccPaymentNotification.STATE_DUPLICATE]
        ), (
            "Le doublon doit être ENREGISTRE et marqué, jamais jeté : le jeter "
            "ferait disparaître la preuve qu'il est arrivé deux fois."
        )
        assert AccPayment.objects.count() == 1
        assert _du(facture) == du_avant - MONTANT_FACTURE


def test_a_still_payable_request_is_never_re_emitted(societe) -> None:
    """**PAY-7, le cas qui coûte de l'argent.** Tant que l'échéance n'est
    pas atteinte, le payeur a le lien en main. Relancer produirait deux
    liens honorables, et l'argent parti ne se reprend pas par une
    transaction de base de données.

    C'est aussi le seul lecteur d'`expires_at` — sans lui, ce champ serait
    une décoration de plus."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        resultat = reemit_intent(intention)

        assert not resultat.emitted_again
        assert resultat.outcome == REEMIT_STILL_PAYABLE
        assert AccPaymentIntent.objects.count() == 1


def test_a_request_already_paid_is_never_re_emitted(societe) -> None:
    """Une notification est arrivée sur cette référence : l'argent a bougé.

    **L'orpheline compte autant que la rapprochée.** « Orpheline » veut
    dire « nous ne savons pas à quoi la rattacher », jamais « elle n'a pas
    eu lieu » — relancer sur cette base redemanderait un paiement déjà
    effectué."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )

    _notifier(societe, reference=intention.external_reference)

    with use_tenant(societe["tenant"].id):
        intention.refresh_from_db()
        # Même échéance dépassée, la notification prime.
        intention.expires_at = timezone.now() - dt.timedelta(days=1)
        intention.save(update_fields=["expires_at"])

        resultat = reemit_intent(intention)
        assert not resultat.emitted_again
        assert resultat.outcome in (REEMIT_SETTLED, REEMIT_NOTIFIED)


def test_an_expired_untransmitted_request_goes_out_again(societe) -> None:
    """Une demande qu'aucun tiers n'a jamais reçue repart, telle quelle.

    **Le scénario est réel, pas construit.** La liaison est suspendue au
    moment de la demande — un raccordement en cours d'ouverture, un
    opérateur qui a coupé —, l'intention est donc créée sans partir. Quand
    la liaison rouvre et que l'échéance est passée, la relance la
    transmet enfin.

    Elle garde SA référence : ce n'est pas une seconde demande, c'est la
    même qui part. Lui en donner une nouvelle laisserait la première
    corrélable pour toujours."""
    with use_tenant(societe["tenant"].id):
        liaison = societe["liaison"]
        liaison.state = FlwLink.STATE_SUSPENDED
        liaison.save(update_fields=["state"])

        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        assert intention.state == AccPaymentIntent.STATE_CREATED, (
            "Sans liaison active, l'intention doit exister sans partir — c'est le "
            "mode d'attente, pas une panne."
        )
        reference_dorigine = intention.external_reference

        liaison.state = FlwLink.STATE_ACTIVE
        liaison.save(update_fields=["state"])
        intention.expires_at = timezone.now() - dt.timedelta(days=1)
        intention.save(update_fields=["expires_at"])

        resultat = reemit_intent(intention)

        assert resultat.emitted_again
        assert resultat.intent is not None
        assert resultat.intent.external_reference == reference_dorigine
        assert AccPaymentIntent.objects.count() == 1
        resultat.intent.refresh_from_db()
        assert resultat.intent.state == AccPaymentIntent.STATE_SENT


def test_re_transmitting_an_already_sent_request_never_raises(societe) -> None:
    """**Un bouton d'écran ne rend jamais 500**, et c'est le test qui l'a
    trouvé.

    La clef d'idempotence se calcule sur (liaison, pièce, opération,
    occurrence) et l'occurrence EST la référence de l'intention : une
    seconde transmission de la même demande heurte donc
    `uniq_flw_exchange_idempotency_key`. Laisser remonter cette collision
    transformait la relance en erreur serveur — alors que la collision ne
    peut désigner qu'une chose : cette demande est déjà partie."""
    from apps.accounting.services.payment_intents import _transmit

    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        intention = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        avant = FlwExchange.objects.filter(operation=OP_INITIATE_PAYMENT).count()

        _transmit(societe["tenant"], intention)

        intention.refresh_from_db()
        assert intention.state == AccPaymentIntent.STATE_SENT
        assert FlwExchange.objects.filter(operation=OP_INITIATE_PAYMENT).count() == avant, (
            "Une seconde transmission a créé un second échange : le tiers "
            "recevrait deux fois la même demande de paiement."
        )


def test_a_second_intent_is_never_emitted_while_the_first_can_be_paid(societe) -> None:
    """**PAY-7** : « aucun double débit n'est possible ». Deux demandes
    vivantes sur la même facture, c'est deux liens que le payeur peut
    honorer tous les deux — et l'argent parti ne se reprend pas par une
    transaction de base de données."""
    with use_tenant(societe["tenant"].id):
        facture = _facture_validee(societe)
        premiere = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        seconde = create_payment_intent(
            societe["tenant"],
            document_type="accounting.AccMove",
            document_id=facture.id,
            amount=MONTANT_FACTURE,
        )
        assert seconde.id == premiere.id
        assert AccPaymentIntent.objects.count() == 1
