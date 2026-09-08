"""S5 — FLX-2 : « Un échec de tiers sur un déclencheur événementiel
n'empêche pas la transition métier : la facture est validée, l'échange est
en file, et l'utilisateur voit l'état réel. »

**Ces tests ne publient JAMAIS d'événement eux-mêmes.** C'est tout leur
intérêt. Les six tests d'`automation` publiaient `workflow.transitioned` à
la main, avec un `tenant_id` explicite — et masquaient ainsi que le vrai
publieur, `core/workflows.py`, n'en fournissait aucun. Aucun déclencheur
branché sur une transition n'aurait pu tirer, et rien ne rougissait.

Ici, on fait transiter une vraie ligne et on regarde ce qui arrive au bout.
"""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.workflow import attempt_transition
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import (
    OP_PUBLISH_DATASET,
    OP_PUSH_DOCUMENT,
    OP_SUBMIT_FOR_VERDICT,
)
from apps.flows.services import triggers
from apps.flows.tests.factories import FlwLinkFactory, FlwTriggerFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    from apps.core import events

    monkeypatch.setattr(events, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _the_generic_subscriber_is_registered():
    """Enregistré UNE SEULE fois par `apps/flows/apps.py::ready()`. Le
    vérifier plutôt que le réenregistrer : réenregistrer masquerait
    précisément l'oubli que cette assertion attrape."""
    from apps.core import events

    assert triggers.dispatch_event_to_triggers in events._WILDCARD_HANDLERS


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S5-DECL", name="Déclencheurs SARL")


def _liaison_avec_declencheur(
    societe, *, operation=OP_SUBMIT_FOR_VERDICT, condition=None, state=None
):
    lien = FlwLinkFactory(tenant=societe, state=state or FlwLink.STATE_ACTIVE)
    FlwTriggerFactory(
        tenant=societe,
        link=lien,
        event_name="workflow.transitioned",
        operation=operation,
        condition=condition or {},
    )
    return lien


def test_a_real_transition_creates_a_queued_exchange(societe) -> None:
    """Le chemin complet : transition métier -> signal `post_transition` ->
    `publish_event` -> bus -> déclencheur -> échange en file. Aucune
    publication à la main."""
    with use_tenant(societe.id):
        lien = _liaison_avec_declencheur(societe)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        echange = FlwExchange.objects.get(link=lien)
    assert echange.state == FlwExchange.STATE_QUEUED, (
        "Le déclencheur a émis lui-même : la durée d'une validation métier "
        "dépendrait alors de la latence du tiers, ce que FLX-2 interdit."
    )
    assert echange.operation == OP_SUBMIT_FOR_VERDICT


def test_the_exchange_carries_the_business_record_it_came_from(societe) -> None:
    """Sans la pièce, l'utilisateur ne « voit » rien : `list_exchanges_for_
    document` est ce qui affiche l'état réel sur la fiche de la facture."""
    from apps.flows.services.public import list_exchanges_for_document

    with use_tenant(societe.id):
        _liaison_avec_declencheur(societe)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        historique = list_exchanges_for_document(
            societe, document_type="core.SampleTenantScopedRecord", document_id=enregistrement.id
        )
    assert len(historique) == 1
    assert historique[0]["state"] == FlwExchange.STATE_QUEUED


def test_a_broken_trigger_never_undoes_the_business_transition(societe, monkeypatch) -> None:
    """**LE critère.** Le déclencheur explose ; la transition métier tient.

    **Avertissement mesuré, et il compte plus que le test lui-même.** Trois
    couches indépendantes tiennent cet invariant : `publish_event` distribue
    sur `on_commit` (la transaction métier est déjà validée), `dispatch_
    event` attrape toute exception de handler dans sa boucle de reprise, et
    `dispatch_event_to_triggers` attrape par déclencheur. La falsification a
    montré qu'**aucune mutation isolée de ces trois couches ne fait rougir
    ce test** — il a fallu les retirer TOUTES LES TROIS pour que la
    transition soit défaite (l'exception remonte alors jusqu'à
    `attempt_transition`, et l'enregistrement reste en `draft`).

    Ce test garde donc l'invariant de bout en bout, pas une couche en
    particulier. Le corollaire est désagréable et doit être écrit : celui
    qui supprimera l'une des trois ne verra rien rougir. C'est le même
    constat que la corrélation de S4, et il se traite pareil — en le
    disant."""

    def _explose(trigger, payload, **_kwargs):
        raise RuntimeError("le tiers est injoignable")

    monkeypatch.setattr(triggers, "fire", _explose)

    with use_tenant(societe.id):
        lien = _liaison_avec_declencheur(societe)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        relu = SampleTenantScopedRecord.objects.get(pk=enregistrement.pk)
        assert relu.state == SampleTenantScopedRecord.STATE_SUBMITTED, (
            "La transition métier a été défaite par l'échec d'un déclencheur : FLX-2 est violé."
        )
        assert not FlwExchange.objects.filter(link=lien).exists()


def test_one_broken_trigger_never_silences_the_others(societe, monkeypatch) -> None:
    """La troisième propriété, la seule qui soit écrite dans le service : un
    déclencheur cassé n'empêche pas les autres déclencheurs du même
    événement de partir. Sans elle, une liaison mal configurée priverait
    l'entreprise de TOUTES ses intégrations."""
    original = triggers.fire

    cassee_id = None

    def _explose_pour_la_premiere(trigger, payload, **kwargs):
        if trigger.link_id == cassee_id:
            raise RuntimeError("le tiers est injoignable")
        return original(trigger, payload, **kwargs)

    monkeypatch.setattr(triggers, "fire", _explose_pour_la_premiere)

    with use_tenant(societe.id):
        cassee = _liaison_avec_declencheur(societe, operation=OP_PUSH_DOCUMENT)
        cassee_id = cassee.id
        saine = _liaison_avec_declencheur(societe, operation=OP_SUBMIT_FOR_VERDICT)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        assert FlwExchange.objects.filter(link=saine).count() == 1
        assert FlwExchange.objects.filter(link=cassee).count() == 0


def test_a_legacy_expression_condition_fires_nothing(societe) -> None:
    """T0 (axe A1) : « jamais une expression libre ».

    Les conditions saisies avant T0 portent la clef `expression` et restent
    en base telles quelles — aucune migration ne les convertit, parce que
    deviner l'intention de leur auteur et se tromper ÉLARGIRAIT la portée
    d'un déclencheur. Elles cessent donc simplement de tirer : ne rien
    envoyer est le seul sens dans lequel une erreur d'interprétation est
    rattrapable. Le filtre déclaratif qui les remplace est mesuré dans
    `test_t0_source_schema.py`, de bout en bout."""
    with use_tenant(societe.id):
        lien = _liaison_avec_declencheur(
            societe, condition={"expression": "payload['target'] == 'submitted'"}
        )
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)  # -> 'submitted'
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        assert not FlwExchange.objects.filter(link=lien).exists(), (
            "Une condition portant l'ancienne clef `expression` a déclenché un "
            "échange : elle a donc été ignorée plutôt que refusée, et la portée "
            "du déclencheur s'est élargie toute seule."
        )


def test_an_unreadable_condition_fires_nothing(societe) -> None:
    """Deny-by-default. Une condition qu'on ne sait pas évaluer ne doit
    RIEN envoyer : l'inverse ferait partir une pièce vers un tiers sur la
    foi d'un filtre que personne n'a su lire."""
    assert triggers.passes_condition({"expression": "__import__('os')"}, {"target": "x"}) is False
    assert triggers.passes_condition({"filters": "pas une liste"}, {"target": "x"}) is False
    assert triggers.passes_condition({"filters": [{"op": "regex"}]}, {"target": "x"}) is False
    assert triggers.passes_condition({}, {"target": "x"}) is True


def test_a_draft_link_never_fires(societe) -> None:
    with use_tenant(societe.id):
        brouillon = _liaison_avec_declencheur(societe, state=FlwLink.STATE_DRAFT)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        assert not FlwExchange.objects.filter(link=brouillon).exists()


def test_a_transition_never_fires_another_company_s_trigger(societe) -> None:
    """Le témoin que la société portée par l'événement est bien LUE — sans
    lui, un `tenant_id` constant quelconque suffirait à faire passer le
    premier test."""
    autre = Tenant.objects.create(code="S5-DECL-B", name="Autre SARL")
    with use_tenant(societe.id):
        chez_a = _liaison_avec_declencheur(societe, operation=OP_PUSH_DOCUMENT)
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe, label="dossier")
    with use_tenant(autre.id):
        chez_b = _liaison_avec_declencheur(autre, operation=OP_PUBLISH_DATASET)

    with use_tenant(societe.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    with use_tenant(societe.id):
        assert FlwExchange.objects.filter(link=chez_a).count() == 1
    with use_tenant(autre.id):
        assert not FlwExchange.objects.filter(link=chez_b).exists()
