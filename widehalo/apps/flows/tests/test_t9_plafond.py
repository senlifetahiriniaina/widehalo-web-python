"""T9 (CON-5, §15.2) — le plafond opposable, et l'alerte AVANT l'atteinte.

**Le critere** : « Une alerte est émise à l'approche d'un plafond, avant
son atteinte, au destinataire configuré. »

**Ce que la mesure disait avant d'écrire, et qui a reclassé le lot.** CON-5
se lit comme une alerte posée sur un plafond existant. Le plafond
n'existait pas. Ce qui existait, en revanche, était troublant de
cohérence :

- `cost.py::cost_total` calculait le total imputé d'une période et n'avait
  **aucun appelant de production** ;
- `FlwExchange.STATE_SUSPENDED` figurait dans la machine à états avec son
  invariant écrit — « un plafond atteint n'ouvre pas d'incident » — et les
  deux transitions nécessaires, `en_file → suspendu` et `suspendu →
  en_file` (« le plafond est relevé ou le mois change : l'échange
  repart ») — et **rien ne l'écrivait** ;
- `incidents.py` proposait comme action de reprise « relever le plafond de
  la liaison », pour un plafond qui n'était un champ nulle part.

Un compteur, un état et une action de reprise, tous les trois écrits,
documentés, cohérents entre eux — et aucun branché. La variante la plus
complète du motif « rien de décoratif » de toute cette vague.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwIncident, FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services.cost_cap import budget_for, month_bounds
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import CallOutcome, drain_outbound_queue
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db

PLAFOND = Decimal("1000.00")
#: Le coût qu'impute l'adaptateur d'essai à chaque envoi. Choisi pour que
#: deux envois franchissent le seuil de 80 % sans atteindre le plafond, et
#: que le troisième l'atteigne — les trois cas du critère en une série.
COUT_PAR_ENVOI = Decimal("400.00")


@pytest.fixture
def destinataire() -> User:
    return User.objects.create_user(email="exploitant-t9@example.com", password="Str0ngPassw0rd!23")


@pytest.fixture
def liaison(destinataire: User):
    tenant = Tenant.objects.create(code="T9-CAP", name="Plafond opposable")
    with use_tenant(tenant.id):
        connecteur = FlwConnectorFactory(tenant=tenant, code="mvola")
        lien = FlwLinkFactory(
            tenant=tenant,
            connector=connecteur,
            state=FlwLink.STATE_ACTIVE,
            monthly_cost_cap_ariary=PLAFOND,
            cost_alert_threshold_pct=80,
            alert_recipient=destinataire,
        )
    return tenant, lien


def _mettre_en_file(tenant, lien, count: int = 1) -> list[FlwExchange]:
    echanges = []
    for index in range(count):
        echange = prepare_exchange(
            tenant, lien, operation=OP_PUSH_DOCUMENT, body=f'{{"rang": {index}}}'
        )
        transition_exchange(echange, to_state=FlwExchange.STATE_QUEUED)
        echanges.append(echange)
    return echanges


def _adaptateur_facturant(cout: Decimal = COUT_PAR_ENVOI):
    """Un adaptateur qui réussit ET impute un coût — c'est la seule façon
    d'exercer un plafond : sans coût imputé, le total reste à zéro et le
    plafond ne se déclenche jamais."""
    appels = []

    def sender(exchange, budget):
        appels.append(exchange.id)
        exchange.cost_ariary = cout
        exchange.cost_unit = "message"
        exchange.save(update_fields=["cost_ariary", "cost_unit"])
        return CallOutcome(ok=True, result_code="200")

    sender.appels = appels
    return sender


def test_without_a_cap_nothing_changes(liaison) -> None:
    """`None` signifie « aucun plafond configuré », jamais « plafond à
    zéro ». Un plafond implicite à zéro bloquerait tout envoi dès la
    première liaison créée — c'est la convention déjà retenue pour le
    plafond de messagerie, et la seule qui ne casse pas l'existant."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        FlwLink.objects.filter(id=lien.id).update(monthly_cost_cap_ariary=None)
        lien.refresh_from_db()
        _mettre_en_file(tenant, lien, count=3)
        envoyeur = _adaptateur_facturant()

        comptes = drain_outbound_queue(tenant, sender=envoyeur)

    assert comptes["sent"] == 3
    assert comptes["skipped_cost_cap"] == 0


def test_the_cap_suspends_without_opening_an_incident(liaison) -> None:
    """**Le cœur du §15.2** : « les échanges passent au statut suspendu,
    l'utilisateur est averti, et la reprise est une décision explicite ».

    Et l'invariant 3 de la machine à états, écrit au sprint S2 et jamais
    exercé jusqu'ici : un plafond atteint **n'ouvre pas d'incident**. Ce
    n'est pas une panne, c'est une décision — l'y assimiler noierait les
    vraies pannes dans la console."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=4)
        envoyeur = _adaptateur_facturant()

        comptes = drain_outbound_queue(tenant, sender=envoyeur)

        # 400 + 400 = 800 < 1000, le troisième porte le total à 1200 : les
        # deux premiers partent, le troisième aussi (le plafond n'était pas
        # encore atteint quand on l'a évalué), le quatrième est suspendu.
        assert comptes["skipped_cost_cap"] >= 1
        suspendus = FlwExchange.objects.filter(state=FlwExchange.STATE_SUSPENDED)
        assert suspendus.exists(), "Le plafond atteint n'a suspendu aucun échange."
        assert not FlwIncident.objects.exists(), (
            "Un plafond atteint a ouvert un incident : c'est une décision, "
            "pas une panne — invariant 3 de la machine à états."
        )


def test_a_suspended_exchange_makes_no_network_call(liaison) -> None:
    """Compter les appels est le seul moyen de le vérifier. Assurer que
    l'état n'a pas bougé laisserait passer une implémentation qui appelle
    le tiers puis ignore la réponse — et le plafond est justement là pour
    ne PAS payer cet appel."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=4)
        envoyeur = _adaptateur_facturant()

        drain_outbound_queue(tenant, sender=envoyeur)

        suspendus = FlwExchange.objects.filter(state=FlwExchange.STATE_SUSPENDED).count()
        assert suspendus >= 1
        assert len(envoyeur.appels) == 4 - suspendus, (
            "Un échange suspendu a tout de même appelé le tiers : le plafond "
            "ne borne alors rien du tout."
        )


def test_the_approach_alerts_before_the_cap_is_reached(liaison, destinataire) -> None:
    """**LE critère, et il tient dans le mot « avant ».** Alerter à 100 %
    tiendrait la lettre du mot « alerte » et manquerait l'exigence : « une
    alerte est émise à l'approche d'un plafond, AVANT son atteinte »."""
    from apps.core.models.notification import Notification

    tenant, lien = liaison
    with use_tenant(tenant.id):
        # Deux envois : 800 sur 1000, soit 80 % — le seuil, pas le plafond.
        _mettre_en_file(tenant, lien, count=2)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant())

        lien.refresh_from_db()

    assert lien.cost_alerted_for_month == month_bounds(timezone.now())[0].date()
    approches = Notification.objects.filter(notification_type="flows.cost_cap_approaching")
    assert approches.count() == 1, (
        "L'approche du plafond n'a pas alerté, ou a alerté plusieurs fois."
    )
    assert approches.first().user_id == destinataire.id


def test_the_approach_alerts_only_once_per_period(liaison) -> None:
    """Le §10.1 refuse qu'un avertissement devienne du bruit. Un plafond
    atteint sans avertissement est vécu comme une panne — mais trente
    avertissements pour le même plafond le sont tout autant, et le
    trente-et-unième ne sera plus lu."""
    from apps.core.models.notification import Notification

    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=2)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant())

        # **La seconde passe doit rester DANS la bande d'approche**, et cette
        # précision n'est pas cosmétique : la première version de ce test
        # renvoyait un second échange à 400, ce qui portait le total à 1 200
        # — au-delà du plafond. `approaching` devenait faux par
        # court-circuit, aucune alerte n'était due, et le test passait sans
        # rien exercer. La falsification F71 l'a démasqué en NE le faisant
        # PAS tomber. Un coût faible garde 850 sur 1 000 : toujours au-dessus
        # du seuil, toujours sous le plafond, donc une seconde alerte serait
        # bel et bien due si rien ne la retenait.
        _mettre_en_file(tenant, lien, count=1)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant(Decimal("50.00")))

        budget = budget_for(lien, now=timezone.now())
        assert budget.approaching is True, "Le test ne se place plus dans la bande d'approche."

    assert Notification.objects.filter(notification_type="flows.cost_cap_approaching").count() == 1


def test_a_link_without_a_recipient_alerts_nobody_but_still_remembers(liaison) -> None:
    """Sans destinataire configuré, rien n'est émis — envoyer à un rôle par
    défaut ferait recevoir à quelqu'un une alerte qu'il n'a pas demandée,
    sur une liaison qu'il ne connaît pas.

    **La marque est posée quand même**, et c'est le point : sans elle, le
    jour où un destinataire serait configuré, il recevrait d'un coup
    l'alerte de tout un mois."""
    from apps.core.models.notification import Notification

    tenant, lien = liaison
    with use_tenant(tenant.id):
        FlwLink.objects.filter(id=lien.id).update(alert_recipient=None)
        lien.refresh_from_db()
        _mettre_en_file(tenant, lien, count=2)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant())
        lien.refresh_from_db()

    assert not Notification.objects.filter(notification_type="flows.cost_cap_approaching").exists()
    assert lien.cost_alerted_for_month is not None


def test_the_budget_is_read_for_the_calendar_month_and_not_a_sliding_window(
    liaison,
) -> None:
    """Le §15.2 parle d'une « restitution mensuelle », et une facture de
    tiers se lit par mois. Une fenêtre glissante de trente jours rendrait la
    jauge irréconciliable avec la facture qu'elle est censée expliquer."""
    tenant, lien = liaison
    maintenant = timezone.now()
    debut, fin = month_bounds(maintenant)

    assert debut.day == 1
    assert debut <= maintenant < fin
    assert (fin - debut).days in (28, 29, 30, 31)


def test_the_gauge_surfaces_an_incomplete_total_instead_of_hiding_it(liaison) -> None:
    """`CostTotal.is_fully_priced` distingue « rien n'a coûté » de « rien
    n'a encore été tarifé », et sa docstring avertit qu'un plafond évalué
    sur un total incomplet laisse passer des envois.

    Suspendre toute une liaison parce qu'un adaptateur n'a pas encore
    imputé son coût ferait d'un retard de tarification une panne
    d'exploitation. Le total connu est donc une **borne inférieure**, et
    l'incomplétude remonte à la jauge pour que l'exploitant la voie au lieu
    de la subir."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=2)  # en file, jamais tarifés

        budget = budget_for(lien, now=timezone.now())

    assert budget.complete is False
    assert budget.spent == Decimal(0)
    assert budget.reached is False


def test_the_gauge_reports_a_ratio_against_the_cap(liaison) -> None:
    """La jauge du §10.2 : « consommation face au plafond, par catégorie et
    par période »."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=2)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant())

        budget = budget_for(lien, now=timezone.now())

    assert budget.spent == COUT_PAR_ENVOI * 2
    assert budget.ratio_pct == 80
    assert budget.approaching is True
    assert budget.reached is False


def test_a_new_month_starts_from_zero(liaison) -> None:
    """« Le plafond est relevé ou le mois change : l'échange repart » — le
    commentaire de la transition `suspendu → en_file`, écrit au sprint S2 et
    jamais exercé jusqu'à ce lot."""
    tenant, lien = liaison
    with use_tenant(tenant.id):
        _mettre_en_file(tenant, lien, count=2)
        drain_outbound_queue(tenant, sender=_adaptateur_facturant())

        mois_suivant = timezone.now() + dt.timedelta(days=32)
        budget = budget_for(lien, now=mois_suivant)

    assert budget.spent == Decimal(0)
    assert budget.approaching is False
    assert budget.already_alerted is False
