"""C-3 — le socle « quelle est la suite ? ».

**La propriete centrale, et pourquoi elle n'allait pas de soi.**
`django_fsm` expose `get_available_user_FIELD_transitions(user)`, presente
dans la bibliotheque installee et appelee nulle part dans ce depot avant
ce lot. Elle paraissait etre la reponse complete a « que peut faire cet
utilisateur ». Elle ne l'est pas : elle filtre sur le `permission=` que
chaque transition declare, et **112 transitions du depot, 3 en
declarent un**. Employee seule, elle proposerait a un `controleur_gestion`
— qui n'a que la LECTURE sur `sales` et `accounting` — de confirmer une
commande.

Ces tests verifient donc les DEUX moities : ce que la machine autorise, et
ce que le droit d'ecriture de C-1 permet. Le premier test est celui qui
tombe si l'on retire la seconde.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.next_steps import (
    NextStep,
    next_steps_for,
    register_next_steps,
    registered_models,
)
from apps.core.tests.utils import grant_module_access, use_tenant
from apps.sales.services.orders import create_order

pytestmark = pytest.mark.django_db


def _societe_et_utilisateur(*modules: str) -> tuple[Tenant, User]:
    tenant = Tenant.objects.create(code="C3", name="Societe C-3")
    user = User.objects.create_user(email="c3@example.com", password="Str0ngPassw0rd!23")
    if modules:
        grant_module_access(user, *modules)
    return tenant, user


def test_a_user_without_the_write_right_is_offered_nothing() -> None:
    """La moitie que la machine a etats ne connait pas.

    C'est LE test du lot : il tombe des qu'on retire la verification du
    droit d'ecriture de `fsm_next_steps`, et il tomberait aussi si l'on
    s'en remettait a `get_available_user_FIELD_transitions` seule — ce qui
    etait la conception evidente avant de mesurer que 109 transitions sur
    112 ne declarent aucune permission."""
    tenant, sans_droit = _societe_et_utilisateur()
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    assert next_steps_for(commande, sans_droit) == [], (
        "Une commande propose des suites a un utilisateur qui n'a aucun droit "
        "d'ecriture sur `sales` : la machine a etats ignore le RBAC, et c'est au "
        "socle de le savoir."
    )


def test_a_user_with_the_write_right_is_offered_what_the_state_allows() -> None:
    """La falsification du test precedent : une garde qui ne proposerait
    JAMAIS rien le ferait passer sans rien prouver."""
    tenant, dote = _societe_et_utilisateur("sales")
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

    suites = next_steps_for(commande, dote)
    assert suites, "Un utilisateur dote ne recoit aucune suite : le socle ne propose rien."
    codes = {s.code for s in suites}
    assert "send" in codes, f"Une commande en brouillon doit pouvoir etre envoyee ; recu {codes}."
    assert all(s.label and s.label != s.code for s in suites), (
        f"Une suite est rendue sans libelle lisible : {[(s.code, s.label) for s in suites]}. "
        f"`core` ne peut pas deviner qu'une transition `confirm` se dit « Confirmer la "
        f"commande » — c'est au module de le declarer."
    )


def test_the_offered_steps_follow_the_state() -> None:
    """Une suite proposee depuis le mauvais etat serait un cul-de-sac."""
    tenant, dote = _societe_et_utilisateur("sales")
    with use_tenant(tenant.id):
        commande = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    avant = {s.code for s in next_steps_for(commande, dote)}

    with use_tenant(tenant.id):
        commande.send()
        commande.save()
    apres = {s.code for s in next_steps_for(commande, dote)}

    assert avant != apres, (
        f"Les suites ne changent pas quand l'etat change ({avant}) : elles ne "
        f"viennent donc pas de la machine a etats."
    )
    assert "send" not in apres, "Une commande deja envoyee propose encore de l'envoyer."


def test_a_model_without_a_resolver_offers_nothing_rather_than_failing() -> None:
    """Tous les documents n'ont pas de processus.

    Un ecran sans suite doit n'en proposer aucune, jamais lever — sans quoi
    poser le bandeau de C-4 sur un ecran quelconque le casserait."""
    tenant, user = _societe_et_utilisateur()
    assert next_steps_for(tenant, user) == []


def test_two_resolvers_for_the_same_model_are_refused() -> None:
    """Deux reponses concurrentes a « quelle est la suite » donneraient deux
    ecrans qui se contredisent, et le dernier `ready()` execute gagnerait —
    c'est-a-dire personne en particulier."""

    def resolveur_a(_instance: object, _user: User) -> list[NextStep]:
        return []

    def resolveur_b(_instance: object, _user: User) -> list[NextStep]:
        return []

    register_next_steps("core.Faux", resolveur_a)
    register_next_steps("core.Faux", resolveur_a)  # idempotent : meme resolveur
    with pytest.raises(ValueError, match="Deux resolveurs"):
        register_next_steps("core.Faux", resolveur_b)


def test_every_prioritised_module_declares_its_documents() -> None:
    """Auto-test du registre : s'il se vidait, tous les tests ci-dessus
    passeraient sur zero resolveur et le bandeau de C-4 serait vide
    partout, sans que rien ne rougisse."""
    attendus = {
        "sales.SalesOrder",
        "sales.SalesQuotation",
        "accounting.AccMove",
        "logistics.LogShipment",
        "logistics.LogTrip",
        "crm.CrmLead",
    }
    manquants = sorted(attendus - registered_models())
    assert not manquants, (
        f"Ces documents n'ont plus de resolveur de suites : {manquants}. Leur module "
        f"ne l'appelle plus depuis `apps.py::ready()`."
    )
