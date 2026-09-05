"""L8 — le dictionnaire d'indicateurs cesse d'etre vide, et calculable
sans modification de code.

**Le defaut ferme ici.** `AnMetricDefinition` etait presentee, dans sa
propre docstring de module, comme « la SEULE voie declaree d'acces aux
donnees decisionnelles ». Rien ne la peuplait : aucune migration, aucune
commande, aucun chemin de creation de tenant. Sur une instance neuve
l'ecran du dictionnaire etait vide, aucun rapport BI ne pouvait nommer un
indicateur, et `strategy` refusait tout resultat cle adosse a un code
(STR-1) puisque aucun code n'existait. Sixieme occurrence du meme patron
dans ce depot : du code correct, correctement documente, que rien
n'invoque ni ne seme.

**Le second defaut.** La correspondance « quel fait calcule cet
indicateur » vivait dans `apps.bi.services.metric_computers.METRIC_FACTS`,
un dictionnaire Python fige. Un indicateur cree a l'execution — par un
client, par l'ecran, par l'API — n'etait donc JAMAIS calculable sans une
modification de code et un deploiement. Le dictionnaire etait gouverne en
apparence, ferme en pratique. Le fait est desormais un champ de
l'indicateur, valide contre les faits reellement exposes.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import available_facts, register_metric
from apps.analytics.services.fact_specs import FACT_SPECS
from apps.analytics.services.public import aggregate_fact, list_available_facts
from apps.analytics.services.starting_metrics import STARTING_METRICS, load_metric_dictionary
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def metrics_tenant() -> Tenant:
    return Tenant.objects.create(code="AN-L8", name="Analytics L8 Tenant")


# ---------------------------------------------------------------------------
# Le jeu de depart
# ---------------------------------------------------------------------------


def test_the_starting_dictionary_is_not_empty(metrics_tenant: Tenant) -> None:
    """Le defaut lui-meme : un tenant sans chargement n'a AUCUN indicateur,
    et en a huit apres."""
    with use_tenant(metrics_tenant.id):
        assert AnMetricDefinition.objects.filter(tenant=metrics_tenant).count() == 0

        total = load_metric_dictionary(metrics_tenant)

        assert total == len(STARTING_METRICS)
        assert total >= 8


def test_every_starting_metric_is_published_and_computable(metrics_tenant: Tenant) -> None:
    """« Calculable » n'est pas une intention : chaque indicateur du jeu
    porte un fait reellement expose par l'entrepot et des axes que ce fait
    sait produire, et le prouve en s'agregeant sans erreur."""
    with use_tenant(metrics_tenant.id):
        load_metric_dictionary(metrics_tenant)

        for metric in AnMetricDefinition.objects.filter(tenant=metrics_tenant, is_current=True):
            assert metric.statut == AnMetricDefinition.STATUT_PUBLIE, metric.code
            assert metric.fait_source, metric.code
            spec = FACT_SPECS[metric.fait_source]
            assert set(metric.axes_autorises) <= set(spec.dimension_fields), metric.code
            # Agregation reelle sur un entrepot vide : une liste, jamais
            # `None` (qui signalerait un fait ou un axe inconnu).
            rows = aggregate_fact(
                metrics_tenant,
                fact=metric.fait_source,
                dimensions=list(metric.axes_autorises),
                filters=[],
            )
            assert rows is not None, metric.code


def test_every_starting_metric_names_its_roles(metrics_tenant: Tenant) -> None:
    """`roles_autorises` vide signifie « aucune restriction » (cf.
    `bi.services.query::_is_metric_authorized`). Un jeu de depart livre
    sans roles ouvrirait donc la masse salariale a tout le monde — ce
    n'est pas un defaut theorique, c'est le comportement par defaut."""
    with use_tenant(metrics_tenant.id):
        load_metric_dictionary(metrics_tenant)

        for metric in AnMetricDefinition.objects.filter(tenant=metrics_tenant, is_current=True):
            assert metric.roles_autorises, metric.code


def test_loading_twice_creates_no_second_version(metrics_tenant: Tenant) -> None:
    """Idempotence reelle, pas seulement « ne leve pas » : une seconde
    execution ne doit creer aucune version supplementaire, sans quoi
    chaque creation de tenant rejouee polluerait l'historique BI-9."""
    with use_tenant(metrics_tenant.id):
        load_metric_dictionary(metrics_tenant)
        rows_after_first = AnMetricDefinition.objects.filter(tenant=metrics_tenant).count()

        load_metric_dictionary(metrics_tenant)

        assert AnMetricDefinition.objects.filter(tenant=metrics_tenant).count() == (
            rows_after_first
        )


# ---------------------------------------------------------------------------
# Calculable sans modification de code
# ---------------------------------------------------------------------------


def test_a_metric_created_at_runtime_is_computable(metrics_tenant: Tenant) -> None:
    """Le coeur de L8. Avant ce lot, un indicateur cree a l'execution
    n'avait aucun moyen de designer son fait : la correspondance vivait
    dans un dictionnaire Python de `bi`. Il fallait modifier du code et
    deployer pour qu'un indicateur du catalogue devienne calculable."""
    with use_tenant(metrics_tenant.id):
        metric = register_metric(
            metrics_tenant,
            code="client.mon_indicateur",
            libelle="Indicateur maison",
            module_source="sales",
            fait_source="vente",
            axes_autorises=["temps", "article"],
            roles_autorises=["direction"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )

        assert metric.fait_source == "vente"
        rows = aggregate_fact(
            metrics_tenant, fact=metric.fait_source, dimensions=["article"], filters=[]
        )
        assert rows is not None


def test_an_unknown_fact_is_refused(metrics_tenant: Tenant) -> None:
    """Lever plutot qu'accepter : un indicateur rattache a un fait
    inexistant se comporterait comme calculable jusqu'a la premiere
    consultation, ou il disparaitrait du rapport."""
    with use_tenant(metrics_tenant.id), pytest.raises(ValidationError, match="Fait inconnu"):
        register_metric(
            metrics_tenant,
            code="client.faux",
            libelle="Faux",
            module_source="sales",
            fait_source="fait_qui_nexiste_pas",
        )


def test_an_axis_the_fact_cannot_produce_is_refused(metrics_tenant: Tenant) -> None:
    """La garde qui compte vraiment : un axe fantome ne se voit qu'au
    moment ou un utilisateur demande cette ventilation — et elle est alors
    perdue en silence par `run_report`."""
    with use_tenant(metrics_tenant.id), pytest.raises(ValidationError, match="Axe"):
        register_metric(
            metrics_tenant,
            code="client.mauvais_axe",
            libelle="Mauvais axe",
            module_source="accounting",
            fait_source="encaissement",
            # `encaissement` n'expose que temps et tiers.
            axes_autorises=["temps", "article"],
        )


def test_a_descriptive_metric_without_a_fact_is_still_allowed(metrics_tenant: Tenant) -> None:
    """Un indicateur purement descriptif reste un etat legitime du
    dictionnaire — il n'est simplement pas calculable, et `bi` le dit
    desormais au lieu de l'ecarter en silence."""
    with use_tenant(metrics_tenant.id):
        metric = register_metric(
            metrics_tenant,
            code="client.descriptif",
            libelle="Descriptif",
            module_source="sales",
        )
        assert metric.fait_source == ""


# ---------------------------------------------------------------------------
# Le fait de paie, enfin lisible — et cloisonne
# ---------------------------------------------------------------------------


def test_the_payroll_fact_is_queryable_at_last() -> None:
    """`AnFactPaie` etait alimente a chaque rafraichissement depuis le Bloc
    Transverse T4 et absent de `FACT_SPECS` : personne ne pouvait le lire.
    Un fait rafraichi que rien n'interroge est du travail perdu a chaque
    execution."""
    assert "paie" in FACT_SPECS
    assert {"code": "paie", "axes": ["periode", "temps"]} in available_facts()
    assert list_available_facts() == available_facts()


def test_the_payroll_fact_exposes_no_per_employee_axis() -> None:
    """Cloisonnement P5/RG-PAY-9. `AnFactPaie` exclut deja `net_to_pay`
    pour ne jamais restituer la remuneration individuelle ; ouvrir un axe
    par employe restituerait le COUT EMPLOYEUR nominatif et reintroduirait
    exactement la fuite que cette exclusion evite."""
    spec = FACT_SPECS["paie"]
    assert "employe" not in spec.dimension_fields
    assert "employee" not in spec.dimension_fields
    assert not any("employee" in field for field in spec.dimension_fields.values())
    # Le detail est nominatif par construction : aucun champ supplementaire
    # n'est expose au drill-down.
    assert spec.detail_extra_fields == ()


def test_the_payroll_metric_blocks_drill_down(metrics_tenant: Tenant) -> None:
    """La `maille_minimale` de l'indicateur de masse salariale bloque
    l'acces au detail (`bi.services.query::drill_down`) — sans elle, le
    detail d'un fait de paie serait atteignable ligne a ligne."""
    with use_tenant(metrics_tenant.id):
        load_metric_dictionary(metrics_tenant)
        metric = AnMetricDefinition.objects.get(
            tenant=metrics_tenant, code="payroll.masse_salariale_brute", is_current=True
        )
        assert metric.maille_minimale == "employe"


# ---------------------------------------------------------------------------
# Un tenant neuf naît avec son dictionnaire
# ---------------------------------------------------------------------------


def test_a_freshly_created_tenant_has_a_populated_dictionary() -> None:
    """La non-regression du defaut d'origine, prise au bon endroit : ce
    n'est pas la commande qu'il faut verifier, c'est que la creation d'un
    tenant l'appelle."""
    from django.core.management import call_command

    code = f"AN-NEW-{uuid.uuid4().hex[:6]}"
    call_command("create_tenant", code=code, name="Tenant neuf")

    tenant = Tenant.objects.get(code=code)
    with use_tenant(tenant.id):
        codes = set(
            AnMetricDefinition.objects.filter(tenant=tenant, is_current=True).values_list(
                "code", flat=True
            )
        )
    assert codes == {entry["code"] for entry in STARTING_METRICS}
