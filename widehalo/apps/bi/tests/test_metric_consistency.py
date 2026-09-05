"""BI-1 (L8) — « test de coherence entre deux ecrans ».

L'audit relevait que ce test « n'a pas ete trouve ». Il porte sur ce que le
critere demande vraiment : deux ecrans qui affichent le MEME indicateur sur
le MEME perimetre doivent afficher le meme chiffre.

**Les deux ecrans, concretement.** Le rapport BI (`services/query.py::
run_report`, ecran `bi`) et la fiche d'objectif de `strategy`, dont le
resultat cle tire son avancement de `services/public.py::
get_metric_current_value`. Ce sont deux chemins de code distincts, ecrits a
des moments differents, sur le meme indicateur du dictionnaire — c'est
precisement la ou une divergence peut naitre sans que personne ne la voie.

**Ce que L8 change pour ce test.** Les deux chemins lisaient le fait dans
`METRIC_FACTS`, un dictionnaire Python fige : ils ne pouvaient diverger
que par accident d'ecriture. Ils lisent desormais `fait_source` sur
l'indicateur lui-meme, donc la coherence tient a une seule source — et ce
test la verifie plutot que de la supposer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnDimTiersFactory, AnFactVenteFactory
from apps.bi.services.public import get_metric_current_value
from apps.bi.services.query import run_report
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db

METRIC_CODE = "sales.ca_ht"


@pytest.fixture
def consistency_tenant() -> Tenant:
    return Tenant.objects.create(code="BI-COHER", name="BI Coherence Tenant")


def _setup(tenant, *, fait_source: str = "vente"):
    register_metric(
        tenant,
        code=METRIC_CODE,
        libelle="CA HT",
        module_source="sales",
        fait_source=fait_source,
        axes_autorises=["temps", "tiers"],
        statut=AnMetricDefinition.STATUT_PUBLIE,
    )
    tiers = AnDimTiersFactory(tenant=tenant, nom="Client A")
    AnFactVenteFactory(tenant=tenant, dim_tiers=tiers, montant_ht_mga=Decimal("12000"))
    AnFactVenteFactory(tenant=tenant, dim_tiers=tiers, montant_ht_mga=Decimal("3000"))
    user = UserFactory()
    grant_role(user, "direction")
    return user


def test_the_report_screen_and_the_objective_screen_agree(consistency_tenant: Tenant) -> None:
    """Le critere lui-meme, a l'ariary pres."""
    with use_tenant(consistency_tenant.id):
        user = _setup(consistency_tenant)
        report = BiReportFactory(
            tenant=consistency_tenant,
            definition={"metric_codes": [METRIC_CODE], "dimensions": [], "filters": []},
        )

        report_rows = run_report(consistency_tenant, report, user)["metrics"][METRIC_CODE]["rows"]
        report_total = Decimal(str(report_rows[0]["value"]))
        objective_value = get_metric_current_value(consistency_tenant, METRIC_CODE, user)

        assert report_total == Decimal("15000")
        assert objective_value == report_total


def test_the_two_screens_still_agree_once_the_report_is_broken_down(
    consistency_tenant: Tenant,
) -> None:
    """La ventilation ne doit pas changer le total. Une somme de lignes
    ventilees qui ne retombe pas sur la valeur non ventilee est le defaut
    classique d'un moteur d'agregation — et il resterait invisible tant
    que personne ne compare les deux."""
    with use_tenant(consistency_tenant.id):
        user = _setup(consistency_tenant)
        AnFactVenteFactory(
            tenant=consistency_tenant,
            dim_tiers=AnDimTiersFactory(tenant=consistency_tenant, nom="Client B"),
            montant_ht_mga=Decimal("5000"),
        )
        report = BiReportFactory(
            tenant=consistency_tenant,
            definition={"metric_codes": [METRIC_CODE], "dimensions": ["tiers"], "filters": []},
        )

        rows = run_report(consistency_tenant, report, user)["metrics"][METRIC_CODE]["rows"]
        breakdown_total = sum((Decimal(str(row["value"])) for row in rows), Decimal(0))

        assert len(rows) == 2
        assert breakdown_total == get_metric_current_value(consistency_tenant, METRIC_CODE, user)


def test_the_two_screens_move_together_when_the_source_changes(
    consistency_tenant: Tenant,
) -> None:
    """Sans ce troisieme test, l'egalite pourrait tenir par hasard.

    Le meme code d'indicateur est rattache a un AUTRE fait, vide celui-la.
    Les deux ecrans doivent alors afficher zero ENSEMBLE — pas l'un
    15 000 et l'autre zero. C'est la propriete qui compte : ils lisent la
    meme source, quelle qu'elle soit. Avant L8 cette source etait un
    dictionnaire Python fige dans `bi`, que `fait_source` remplace ; le
    scenario ci-dessous etait alors litteralement inexprimable, le fait
    d'un indicateur n'etant pas modifiable a l'execution."""
    with use_tenant(consistency_tenant.id):
        user = _setup(consistency_tenant, fait_source="encaissement")
        report = BiReportFactory(
            tenant=consistency_tenant,
            definition={"metric_codes": [METRIC_CODE], "dimensions": [], "filters": []},
        )

        rows = run_report(consistency_tenant, report, user)["metrics"][METRIC_CODE]["rows"]
        report_total = Decimal(str(rows[0]["value"]))
        objective_value = get_metric_current_value(consistency_tenant, METRIC_CODE, user)

        # Les ventes existent toujours ; c'est l'indicateur qui ne les
        # regarde plus. Les deux ecrans le constatent de la meme facon.
        assert report_total == Decimal(0)
        assert objective_value == report_total


def test_a_metric_without_a_fact_is_announced_not_dropped(consistency_tenant: Tenant) -> None:
    """L8 : `run_report` ecartait en silence un indicateur non calculable,
    la ou `drill_down` repondait deja « Indicateur non calculable » sur la
    meme condition. Un tableau de bord auquel il manque une ligne sans
    qu'un mot l'explique se lit comme un tableau complet."""
    with use_tenant(consistency_tenant.id):
        user = _setup(consistency_tenant, fait_source="")
        report = BiReportFactory(
            tenant=consistency_tenant,
            definition={"metric_codes": [METRIC_CODE], "dimensions": [], "filters": []},
        )

        result = run_report(consistency_tenant, report, user)

        assert result["metrics"] == {}
        assert any("non calculable" in note for note in result["scope_notes"])


def test_an_unknown_metric_code_is_announced_too(consistency_tenant: Tenant) -> None:
    """Meme discipline pour un code absent du dictionnaire : un rapport qui
    reference un indicateur supprime doit le dire."""
    with use_tenant(consistency_tenant.id):
        user = _setup(consistency_tenant)
        report = BiReportFactory(
            tenant=consistency_tenant,
            definition={"metric_codes": ["code.inexistant"], "dimensions": [], "filters": []},
        )

        result = run_report(consistency_tenant, report, user)

        assert result["metrics"] == {}
        assert any("introuvable" in note for note in result["scope_notes"])
