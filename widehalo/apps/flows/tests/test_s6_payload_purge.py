"""S6, FLX-5 — la purge de la charge utile.

Le critère, mot pour mot : « la purge de la charge utile d'un échange
laisse l'échange, son empreinte, son horodatage et son verdict intacts et
interrogeables ».

**Ce qui manquait.** `FlwPayload.retain_until` était déclaré depuis S1 et
avait exactement deux occurrences dans tout le dépôt : le modèle et sa
migration. Ni lecteur, ni écrivain, ni purge, ni index. La colonne
annonçait une politique de rétention que rien ne faisait vivre — et le
cahier nomme le risque dans les mêmes termes : « fenêtre de purge
dépassée ».
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import list_scheduled_commands
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwLink, FlwPayload
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.payload_purge import purge_expired_payloads
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db

_CORPS = '{"montant": 1500000, "client": "SARL Vohitra"}'


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S6-PURGE", name="Purge SARL")


@pytest.fixture
def liaison(societe):
    with use_tenant(societe.id):
        return FlwLinkFactory(tenant=societe, state=FlwLink.STATE_ACTIVE)


def _echange_tranche(societe, liaison, *, retain_until=None, body=_CORPS):
    """Un échange mené jusqu'à son verdict, avec sa charge utile.

    Jusqu'au VERDICT, et pas seulement jusqu'à `en_file` : le critère parle
    de « verdict intact », et un échange qui n'en a pas ne prouverait rien
    de ce qu'on veut vérifier."""
    echange = prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body=body)
    transition_exchange(echange, to_state=FlwExchange.STATE_QUEUED)
    transition_exchange(echange, to_state=FlwExchange.STATE_SENT, result_code="200")
    transition_exchange(echange, to_state=FlwExchange.STATE_ACCEPTED)
    if body:
        FlwPayload.objects.filter(exchange=echange).update(retain_until=retain_until)
    echange.refresh_from_db()
    return echange


# --- Le critère lui-même -------------------------------------------------------


def test_the_purge_removes_the_payload_and_leaves_the_proof_intact(societe, liaison) -> None:
    """Les quatre survivants que le critère nomme, vérifiés un par un —
    et pas « l'échange existe encore », qui serait vrai d'une ligne vidée
    de tout son contenu."""
    with use_tenant(societe.id):
        echange = _echange_tranche(societe, liaison, retain_until=dt.date(2020, 1, 1))
        empreinte, cree_le, verdict, code = (
            echange.payload_fingerprint,
            echange.created_at,
            echange.state,
            echange.result_code,
        )

        supprimees = purge_expired_payloads()

        assert supprimees == 1
        assert not FlwPayload.objects.filter(exchange=echange).exists()
        echange.refresh_from_db()
        assert echange.payload_fingerprint == empreinte
        assert echange.created_at == cree_le
        assert echange.state == verdict == FlwExchange.STATE_ACCEPTED
        assert echange.result_code == code
        assert FlwExchange.objects.filter(id=echange.id).exists(), (
            "« interrogeables » : l'échange doit rester trouvable par une "
            "requête ordinaire, pas seulement exister."
        )


def test_a_payload_whose_date_has_not_come_survives(societe, liaison) -> None:
    """Le témoin. Sans lui, une purge qui supprimerait TOUT rendrait le test
    précédent vert — c'est le mode d'échec habituel d'un test de
    suppression."""
    with use_tenant(societe.id):
        demain = dt.date.today() + dt.timedelta(days=1)
        echange = _echange_tranche(societe, liaison, retain_until=demain)
        assert purge_expired_payloads() == 0
        assert FlwPayload.objects.filter(exchange=echange).exists()


def test_the_purge_is_idempotent(societe, liaison) -> None:
    """Deux passes ne suppriment pas deux fois. Une purge quotidienne qui
    compterait à nouveau ce qu'elle a déjà supprimé rendrait ses journaux
    d'exploitation illisibles."""
    with use_tenant(societe.id):
        _echange_tranche(societe, liaison, retain_until=dt.date(2020, 1, 1))
        assert purge_expired_payloads() == 1
        assert purge_expired_payloads() == 0


# --- L'arbitrage sur `retain_until` nul ----------------------------------------


@override_settings(FLOWS_PAYLOAD_RETENTION_DAYS=365)
def test_a_payload_without_a_date_falls_under_the_default_policy(societe, liaison) -> None:
    """**L'arbitrage, et son motif.** Nul aurait pu signifier « à garder
    pour toujours ». Ce choix aurait rendu la purge inerte dès le premier
    jour — personne n'écrit ce champ — et aurait fait d'un oubli de saisie
    une conservation perpétuelle de données personnelles, c'est-à-dire
    l'inverse de ce à quoi sert une politique de rétention."""
    with use_tenant(societe.id):
        echange = _echange_tranche(societe, liaison, retain_until=None)
        FlwPayload.objects.filter(exchange=echange).update(
            created_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        )
        assert purge_expired_payloads() == 1
        assert not FlwPayload.objects.filter(exchange=echange).exists()


@override_settings(FLOWS_PAYLOAD_RETENTION_DAYS=365)
def test_a_recent_payload_without_a_date_survives_the_default_policy(societe, liaison) -> None:
    with use_tenant(societe.id):
        echange = _echange_tranche(societe, liaison, retain_until=None)
        assert purge_expired_payloads() == 0
        assert FlwPayload.objects.filter(exchange=echange).exists()


@override_settings(FLOWS_PAYLOAD_RETENTION_DAYS=1)
def test_an_explicit_date_always_wins_over_the_default_policy(societe, liaison) -> None:
    """Dans les deux sens : une soumission fiscale se conserve plus
    longtemps que le défaut, un catalogue publié moins. Ici, le plus long
    l'emporte sur une politique par défaut d'un seul jour."""
    with use_tenant(societe.id):
        echange = _echange_tranche(
            societe, liaison, retain_until=dt.date.today() + dt.timedelta(days=3650)
        )
        FlwPayload.objects.filter(exchange=echange).update(
            created_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        )
        assert purge_expired_payloads() == 0
        assert FlwPayload.objects.filter(exchange=echange).exists()


# --- « Purgée » et « jamais écrite » ne sont pas la même chose -----------------


def test_a_purged_exchange_is_distinguishable_from_one_that_never_carried_a_body(
    societe, liaison
) -> None:
    """La question que `purged_at` aurait dû résoudre, résolue sans colonne
    nouvelle. `FlwPayload` refuse ce drapeau depuis S1 — « une seconde
    source de vérité » — mais laissait la question ouverte. L'empreinte y
    répondait déjà : elle n'est posée qu'à la création, et seulement quand
    un corps existait."""
    with use_tenant(societe.id):
        avec_corps = _echange_tranche(societe, liaison, retain_until=dt.date(2020, 1, 1))
        sans_corps = _echange_tranche(societe, liaison, body="")

        assert avec_corps.payload_is_purged is False, "Pas encore purgée."
        assert sans_corps.payload_is_purged is False

        purge_expired_payloads()
        avec_corps.refresh_from_db()
        sans_corps.refresh_from_db()

        assert avec_corps.payload_is_purged is True
        assert sans_corps.payload_is_purged is False, (
            "Un échange qui n'a jamais porté de corps n'a rien à purger : le "
            "dire « purgé » inventerait une donnée disparue."
        )


# --- Les deux pièces sans lesquelles la purge n'est qu'un bouton ---------------


def test_the_purge_is_declared_in_the_scheduling_registry() -> None:
    """**La leçon déjà payée deux fois dans ce dépôt.** La reprise WhatsApp
    et la file de flux avaient toutes deux un mécanisme sans déclencheur —
    « repris automatiquement » reposait sur quelqu'un qui pense à cliquer.
    Une troisième fois serait une négligence."""
    codes = {commande.code for commande in list_scheduled_commands()}
    assert "flows.purge_payloads" in codes


def test_the_command_runs_and_reports(societe, liaison) -> None:
    with use_tenant(societe.id):
        _echange_tranche(societe, liaison, retain_until=dt.date(2020, 1, 1))
    call_command("purge_flows_payloads")
    with use_tenant(societe.id):
        assert FlwPayload.objects.count() == 0


def test_the_index_the_daily_sweep_needs_exists() -> None:
    """Sans index, la purge parcourt chaque nuit la table la plus
    volumineuse du hub — et le jour où elle devient lente est celui où elle
    cesse d'être exécutée. Même vérification que pour
    `idx_core_idemp_expires` au sprint S4."""
    assert "idx_flw_payload_retention" in {index.name for index in FlwPayload._meta.indexes}


# --- Isolation ------------------------------------------------------------------


def test_one_company_s_purge_never_touches_another_s_payloads(societe, liaison) -> None:
    """`purge_expired_payloads` boucle sur toutes les sociétés — c'est
    exactement la boucle où une erreur d'isolation ne se voit pas, puisque
    tout finit par être traité. Le test qui mord est donc celui d'une
    société dont la charge utile N'EST PAS échue."""
    autre = Tenant.objects.create(code="S6-PURGE-B", name="Autre SARL")
    with use_tenant(societe.id):
        echu = _echange_tranche(societe, liaison, retain_until=dt.date(2020, 1, 1))
    with use_tenant(autre.id):
        liaison_b = FlwLinkFactory(tenant=autre, state=FlwLink.STATE_ACTIVE)
        garde = _echange_tranche(
            autre, liaison_b, retain_until=dt.date.today() + dt.timedelta(days=30)
        )

    assert purge_expired_payloads() == 1

    with use_tenant(societe.id):
        assert not FlwPayload.objects.filter(exchange=echu).exists()
    with use_tenant(autre.id):
        assert FlwPayload.objects.filter(exchange=garde).exists()
