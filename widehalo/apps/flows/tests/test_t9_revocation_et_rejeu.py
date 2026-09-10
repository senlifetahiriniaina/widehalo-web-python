"""T9 (CON-3 et CON-4) — révoquer sans rien effacer, et rejouer sans
facture surprise.

**CON-3** : « Une révocation coupe le connecteur immédiatement, conserve
les échanges passés et propose la purge des charges utiles restantes. »

**CON-4** : « Le panneau de rejeu affiche volume et coût estimé avant
confirmation ; aucun rejeu de masse n'est déclenchable sans cette
estimation. »

**Ce que la mesure disait avant d'écrire.** Pour CON-4, tout existait sauf
l'écran : `estimate_replay` est livrée depuis le sprint S4 et sa docstring
dit littéralement « ce que l'écran doit afficher AVANT que quiconque ne
confirme ». Elle n'a jamais eu d'appelant de production. Pour CON-3,
`FlwLink` n'avait que trois états — brouillon, active, suspendue — et
aucune trace de révocation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwLink, FlwPayload
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import CallOutcome, drain_outbound_queue
from apps.flows.services.replay import estimate_replay, replay_selection
from apps.flows.services.revocation import (
    MOTIF_MINIMUM,
    purge_remaining_payloads,
    remaining_payload_count,
    revoke_link,
)
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db

MOTIF = "Le client a retiré son consentement de sortie le 9 septembre, par courrier."


@pytest.fixture
def exploitant() -> User:
    return User.objects.create_user(
        email="exploitant-con34@example.com", password="Str0ngPassw0rd!23"
    )


@pytest.fixture
def liaison():
    tenant = Tenant.objects.create(code="T9-CON34", name="Révocation et rejeu")
    with use_tenant(tenant.id):
        connecteur = FlwConnectorFactory(tenant=tenant, code="dgi")
        lien = FlwLinkFactory(tenant=tenant, connector=connecteur, state=FlwLink.STATE_ACTIVE)
    return tenant, lien


def _echange(tenant, lien, *, corps: str = '{"x": 1}') -> FlwExchange:
    echange = prepare_exchange(tenant, lien, operation=OP_PUSH_DOCUMENT, body=corps)
    transition_exchange(echange, to_state=FlwExchange.STATE_QUEUED)
    return echange


# --- CON-3 : la révocation ----------------------------------------------------


def test_revocation_cuts_the_connector_immediately(liaison, exploitant) -> None:
    """« Coupe le connecteur IMMÉDIATEMENT. » La vidange ne sert que les
    liaisons actives — c'est donc vrai par construction, et c'est
    précisément pour cela qu'il faut le vérifier : une clause de filtre se
    change, et le jour où elle changerait, la révocation deviendrait
    décorative."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _echange(tenant, lien)
        revoke_link(lien, revoked_by=exploitant, reason=MOTIF)

        appels = []

        def envoyeur(exchange, budget):
            appels.append(exchange.id)
            return CallOutcome(ok=True, result_code="200")

        drain_outbound_queue(tenant, sender=envoyeur)

    assert appels == [], "Une liaison révoquée émet encore : la coupure n'en est pas une."


def test_revocation_keeps_the_past_exchanges(liaison, exploitant) -> None:
    """« Conserve les échanges passés. » Le registre est la preuve de ce qui
    est parti ; une révocation qui l'effacerait serait l'inverse de ce que
    la Phase 4 construit."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        echange = _echange(tenant, lien)
        revoke_link(lien, revoked_by=exploitant, reason=MOTIF)

        assert FlwExchange.objects.filter(id=echange.id).exists()


def test_revocation_is_a_dated_fact_with_its_author_and_reason(liaison, exploitant) -> None:
    """Savoir qu'une liaison a été révoquée le 12 à 14 h est ce qui permet
    de dire si un échange du 12 à 13 h était légitime. Un simple changement
    d'état efface cette question."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        revoke_link(lien, revoked_by=exploitant, reason=MOTIF)
        lien.refresh_from_db()

    assert lien.state == FlwLink.STATE_REVOKED
    assert lien.revoked_at is not None
    assert lien.revoked_by_id == exploitant.id
    assert lien.revoked_reason == MOTIF


def test_a_revocation_without_a_real_reason_is_refused(liaison, exploitant) -> None:
    """Cette décision coupe un canal ; celui qui la relira dans six mois
    doit savoir pourquoi. Même discipline que partout ailleurs dans ce
    dépôt."""
    tenant, lien = liaison
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        revoke_link(lien, revoked_by=exploitant, reason="parce que")

    lien.refresh_from_db()
    assert lien.state == FlwLink.STATE_ACTIVE
    assert MOTIF_MINIMUM >= 40


def test_revoked_is_not_suspended(liaison, exploitant) -> None:
    """**Le point qui justifie un état de plus.** Une liaison suspendue
    reprend : plafond atteint, panne passagère. Une liaison révoquée ne
    reprend pas — le consentement a été retiré. Les confondre laisserait une
    reprise d'exploitation rouvrir un canal fermé délibérément."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        revoke_link(lien, revoked_by=exploitant, reason=MOTIF)
        lien.refresh_from_db()

    assert lien.state != FlwLink.STATE_SUSPENDED
    assert FlwLink.STATE_REVOKED not in (FlwLink.STATE_SUSPENDED, FlwLink.STATE_DRAFT)


def test_the_purge_is_proposed_and_keeps_the_proof(liaison, exploitant) -> None:
    """« PROPOSE la purge » — et la purge, quand elle a lieu, conserve la
    preuve : l'empreinte reste sur l'échange, la charge utile disparaît, et
    `payload_is_purged` distingue ensuite « purgée » de « jamais écrite »
    (FLX-5)."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        echange = _echange(tenant, lien, corps='{"secret_du_client": "à ne pas garder"}')
        assert remaining_payload_count(lien) == 1

        revoke_link(lien, revoked_by=exploitant, reason=MOTIF)
        # La révocation NE purge pas d'elle-même : le contenu peut encore
        # servir à une réclamation ou à un contrôle.
        assert remaining_payload_count(lien) == 1

        purges = purge_remaining_payloads(lien)
        echange.refresh_from_db()

        # **Les assertions restent DANS le contexte de société**, et ce
        # n'est pas un détail de forme : `objects` est un manager en refus
        # par défaut. Hors contexte, `FlwPayload.objects...exists()` rend
        # `False` parce qu'aucune société n'est active — pas parce que la
        # purge a fonctionné. La première version de ce test vérifiait donc
        # la purge de façon parfaitement vide, et n'a été démasquée que
        # parce que l'assertion VOISINE, elle, attendait `True`.
        assert purges == 1
        assert not FlwPayload.objects.filter(exchange=echange).exists()
        assert FlwExchange.objects.filter(id=echange.id).exists()
        assert echange.payload_fingerprint, "L'empreinte doit survivre à la purge (FLX-5)."
        assert echange.payload_is_purged is True


# --- CON-4 : le rejeu supervisé -----------------------------------------------


def _en_echec(tenant, lien, *, cout: Decimal | None = None) -> FlwExchange:
    echange = _echange(tenant, lien)
    transition_exchange(echange, to_state=FlwExchange.STATE_FAILED)
    if cout is not None:
        echange.cost_ariary = cout
        echange.cost_unit = "message"
        echange.save(update_fields=["cost_ariary", "cost_unit"])
    return echange


def test_a_mass_replay_without_the_estimate_is_impossible_by_signature(liaison) -> None:
    """**LE critère, et il tient dans « aucun rejeu de masse n'est
    déclenchable sans cette estimation ».**

    Faire porter la règle à l'écran seul l'aurait rendue contournable en
    appelant le service — exactement la faiblesse refusée pour la garde
    d'activation. L'estimation est donc un paramètre OBLIGATOIRE."""
    import inspect

    signature = inspect.signature(replay_selection)
    parametre = signature.parameters.get("acknowledged")

    assert parametre is not None, "Le rejeu de masse ne demande pas d'estimation."
    assert parametre.default is inspect.Parameter.empty, (
        "L'estimation a une valeur par défaut : un appelant distrait "
        "déclencherait un rejeu de masse sans jamais l'avoir vue."
    )


def test_a_stale_estimate_is_refused(liaison) -> None:
    """Une estimation périmée n'est plus une estimation. Si la sélection a
    changé entre l'affichage et la confirmation, les chiffres ne
    correspondent plus — et confirmer reviendrait à engager une dépense que
    personne n'a vue."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        premier = _en_echec(tenant, lien, cout=Decimal("100.00"))
        vue = estimate_replay(tenant, ids=[premier.id])

        # La sélection s'élargit après l'affichage.
        second = _en_echec(tenant, lien, cout=Decimal("900.00"))

        with pytest.raises(ValidationError) as refus:
            replay_selection(tenant, ids=[premier.id, second.id], acknowledged=vue)

    assert "estimation" in " ".join(refus.value.messages).lower()


def test_a_current_estimate_lets_the_replay_through(liaison) -> None:
    tenant, lien = liaison
    with use_tenant(tenant.id):
        echange = _en_echec(tenant, lien, cout=Decimal("100.00"))
        vue = estimate_replay(tenant, ids=[echange.id])
        successeurs = replay_selection(tenant, ids=[echange.id], acknowledged=vue)

    assert len(successeurs) == 1


def test_the_estimate_says_at_least_when_a_cost_is_missing(liaison) -> None:
    """« Annoncer 12 000 Ar pour une sélection dont la moitié n'est pas
    tarifée, c'est annoncer un plancher en le présentant comme un total. »
    L'écran doit dire « au moins », et `is_cost_certain` est ce qui le lui
    permet."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        tarife = _en_echec(tenant, lien, cout=Decimal("100.00"))
        sans_cout = _en_echec(tenant, lien)

        estimation = estimate_replay(tenant, ids=[tarife.id, sans_cout.id])

    assert estimation.count == 2
    assert estimation.cost_ariary == Decimal("100.00")
    assert estimation.unpriced_count == 1
    assert estimation.is_cost_certain is False
