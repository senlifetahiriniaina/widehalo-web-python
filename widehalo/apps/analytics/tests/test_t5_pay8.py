"""T5 (PAY-8) — le taux de rapprochement devient un indicateur gouverné.

**Le critère** : « le taux de rapprochement automatique des encaissements
est un indicateur gouverné ». « Gouverné » a un sens précis dans ce dépôt :
une entrée d'`AnMetricDefinition`, qui REFUSE tout `fait_source` absent de
`FACT_SPECS`. Un chiffre calculé à part, si juste soit-il, n'est pas
gouverné — il n'est ni versionné, ni autorisé par rôle, ni lisible par
`bi` ou par `strategy`.

**Ce que ce fichier vérifie et qu'aucun test de dictionnaire ne peut
dire.** `test_starting_metrics.py` prouve que les deux indicateurs
s'agrègent sans erreur — sur un entrepôt VIDE. Il ne dit rien de ce
qu'ils comptent. Ici, des notifications réelles traversent le
rafraîchissement, et les deux sommes sont comparées à ce qu'on sait avoir
écrit.

**Pourquoi deux sommes et pas un taux.** `aggregate_fact` ne connaît que
`Sum`, et surtout un taux ne s'agrège pas : la moyenne des taux
quotidiens n'est pas le taux du mois dès que deux jours ont des volumes
différents. Stocker le taux aurait donc produit un indicateur faux à
toute maille sauf celle où il a été calculé. Le rapport se fait chez le
consommateur, sur deux chiffres justes partout.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounting.models import AccPaymentNotification
from apps.analytics.models import AnFactNotificationEncaissement, AnMetricDefinition
from apps.analytics.services.public import aggregate_fact
from apps.analytics.services.refresh import refresh_warehouse_for_tenant
from apps.analytics.services.starting_metrics import load_metric_dictionary
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

VOIE = "agregateur"


@pytest.fixture
def societe():
    return Tenant.objects.create(code="T5-PAY8", name="Indicateur d'encaissement")


def _notification(tenant: Tenant, *, reference: str, etat: str) -> AccPaymentNotification:
    return AccPaymentNotification.objects.create(
        tenant=tenant,
        provider_code=VOIE,
        external_reference=reference,
        amount=Decimal("1000"),
        currency="MGA",
        state=etat,
    )


def test_the_two_metrics_count_what_actually_arrived(societe) -> None:
    """Trois notifications, deux rapprochées : le dénominateur vaut 3 et le
    numérateur 2.

    **Le dénominateur inclut les orphelines, et c'est tout l'enjeu.** Le
    compter depuis les RÈGLEMENTS — ce que `AnFactEncaissement` aurait
    permis — reviendrait à diviser un nombre par lui-même : le taux
    vaudrait toujours 100 %, et l'indicateur dirait exactement l'inverse
    de ce qu'il mesure."""
    with use_tenant(societe.id):
        _notification(societe, reference="A-1", etat=AccPaymentNotification.STATE_MATCHED)
        _notification(societe, reference="A-2", etat=AccPaymentNotification.STATE_MATCHED)
        _notification(societe, reference="A-3", etat=AccPaymentNotification.STATE_ORPHAN)

        refresh_warehouse_for_tenant(societe)

        assert AnFactNotificationEncaissement.objects.count() == 3

        recues = aggregate_fact(
            societe, fact="notif_encaissement", dimensions=["connecteur"], filters=[]
        )
        rapprochees = aggregate_fact(
            societe,
            fact="notif_encaissement_rapproche",
            dimensions=["connecteur"],
            filters=[],
        )

    assert [(row["connecteur"], row["value"]) for row in recues] == [(VOIE, 3)]
    assert [(row["connecteur"], row["value"]) for row in rapprochees] == [(VOIE, 2)]


def test_a_manual_assignment_moves_the_indicator(societe) -> None:
    """**« Ce que le deuxième passage apprend de plus que le premier. »**

    Une orpheline affectée à la main (PAY-3) devient rapprochée. Si le
    fait n'était écrit qu'à la réception, le taux resterait figé sur ce
    qu'il valait à l'arrivée, et le travail de rattrapage de l'exploitant
    n'apparaîtrait jamais dans l'indicateur qui le mesure — un chiffre qui
    tourne sans rien apprendre."""
    with use_tenant(societe.id):
        notification = _notification(
            societe, reference="B-1", etat=AccPaymentNotification.STATE_ORPHAN
        )
        refresh_warehouse_for_tenant(societe)
        avant = aggregate_fact(
            societe, fact="notif_encaissement_rapproche", dimensions=[], filters=[]
        )

        notification.state = AccPaymentNotification.STATE_MATCHED
        notification.save(update_fields=["state"])
        refresh_warehouse_for_tenant(societe)
        apres = aggregate_fact(
            societe, fact="notif_encaissement_rapproche", dimensions=[], filters=[]
        )

        assert AnFactNotificationEncaissement.objects.count() == 1, (
            "Le rafraîchissement a créé une seconde ligne pour la même "
            "notification : le dénominateur doublerait à chaque changement d'état."
        )

    assert avant[0]["value"] == 0
    assert apres[0]["value"] == 1


def test_both_metrics_are_governed_and_readable_by_accountants(societe) -> None:
    """« Gouverné » = une entrée du dictionnaire, publiée, avec ses rôles.

    Un indicateur sans rôles déclarés est ouvert à tout le monde (cf.
    `bi.services.query::_is_metric_authorized`) : le laisser vide ici
    exposerait le détail des encaissements de l'entreprise à n'importe quel
    utilisateur connecté."""
    with use_tenant(societe.id):
        load_metric_dictionary(societe)
        indicateurs = {
            metric.code: metric
            for metric in AnMetricDefinition.objects.filter(tenant=societe, is_current=True)
        }

    for code in ("flows.encaissements_notifies", "flows.encaissements_rapproches"):
        assert code in indicateurs, f"{code} absent du dictionnaire gouverné."
        metric = indicateurs[code]
        assert metric.statut == AnMetricDefinition.STATUT_PUBLIE
        assert metric.roles_autorises, code
        assert set(metric.axes_autorises) == {"temps", "connecteur"}, (
            "PAY-8 demande le taux PAR CONNECTEUR : un taux global qui baisse ne "
            "désigne personne, un taux qui baisse sur une voie désigne "
            "l'opérateur à appeler."
        )
