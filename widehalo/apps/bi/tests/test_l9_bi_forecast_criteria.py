"""L9 — BI et Forecast : le bloquant, et trois critères que rien n'exerçait.

**Le bloquant.** `BiDashboard` avait six occurrences dans tout le dépôt —
sa définition, sa migration de schéma, un import et une lecture dans la
vue, et une factory de test **jamais utilisée**. Aucun `objects.create`,
aucune route d'API d'écriture, aucune commande, aucune fixture, aucun
enregistrement dans l'admin. Or `dashboards` est l'onglet PAR DÉFAUT de
`/bi/` : le premier écran que voit tout utilisateur du module affichait
« Aucun tableau de bord pour votre rôle », structurellement, sur toute
instance. Et aucun test n'échouait — puisque aucun test n'en créait.

C'est la forme la plus pure du motif que ce chantier traque : le modèle
était prêt, la vue savait déjà filtrer et résoudre les tuiles ; il ne
manquait que la voie d'écriture."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.bi.models import BiDashboard
from apps.bi.services.dashboards import (
    create_dashboard,
    ensure_starting_dashboards,
    set_dashboard_tiles,
)
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"


@pytest.fixture
def bi_setup():
    tenant = Tenant.objects.create(code="L9-BI", name="BI L9 SARL")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="l9-bi@example.com", password=PASSWORD)
        # `controleur_gestion` : droits complets sur `bi` et HORS
        # `CORE_MFA_REQUIRED_ROLES` — le dépôt a déjà tranché ce point
        # (`apps/bi/tests/test_views.py`), inutile de le retrancher.
        grant_role(user, "controleur_gestion")
        report = BiReportFactory(tenant=tenant, domaine="ventes", owner=user)
    return tenant, user, report


def _client(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


# --- Le bloquant : la voie d'écriture ------------------------------------------


def test_a_dashboard_can_be_composed_from_the_screen(bi_setup) -> None:
    """Avant L9, AUCUN chemin de production ne créait de `BiDashboard`."""
    tenant, user, report = bi_setup
    client = _client(tenant, user)

    response = client.post(
        "/bi/dashboards/new/",
        {"name": "Pilotage commercial", "report_ids": [str(report.id)]},
    )
    assert response.status_code in (200, 302)

    with use_tenant(tenant.id):
        dashboard = BiDashboard.objects.get(tenant=tenant, name="Pilotage commercial")
    assert dashboard.tiles == [{"report_id": str(report.id), "position": 0, "size": "md"}]


def test_the_default_tab_stops_being_structurally_empty(bi_setup) -> None:
    """L'onglet par défaut de `/bi/` affichait « Aucun tableau de bord »
    à tout le monde. Il propose désormais l'action qui manquait, et
    affiche le tableau dès qu'il existe."""
    tenant, user, report = bi_setup
    client = _client(tenant, user)

    empty = client.get("/bi/").content.decode()
    assert "Composer un tableau de bord" in empty

    with use_tenant(tenant.id):
        create_dashboard(
            tenant,
            name="Mon tableau",
            user=user,
            is_shared=True,
            tiles=[{"report_id": str(report.id)}],
        )
    filled = client.get("/bi/").content.decode()
    assert "Mon tableau" in filled
    assert report.name in filled


def test_a_tile_pointing_at_another_tenants_report_is_refused(bi_setup) -> None:
    """`tiles` est un JSONField dénormalisé : rien en base n'empêche d'y
    écrire l'UUID du rapport d'une autre société. Un tableau de bord dont
    une tuile ne résout pas s'affiche silencieusement amputé — le lecteur
    croit voir tout son tableau."""
    tenant, user, _report = bi_setup
    other = Tenant.objects.create(code="L9-BI-B", name="Autre société")
    with use_tenant(other.id):
        foreign = BiReportFactory(tenant=other)

    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_dashboard(tenant, name="Fuite", user=user, tiles=[{"report_id": str(foreign.id)}])


def test_the_starting_set_never_overwrites_what_the_tenant_changed(bi_setup) -> None:
    """Amorçage idempotent, même discipline que `starting_metrics` (L8)."""
    tenant, user, _report = bi_setup
    with use_tenant(tenant.id):
        first = ensure_starting_dashboards(tenant, user=user)
        assert first, "un rapport publié existe : un tableau de départ doit être créé"

        set_dashboard_tiles(first[0], tiles=[])
        again = ensure_starting_dashboards(tenant, user=user)

        assert again == []
        first[0].refresh_from_db()
        assert first[0].tiles == []


# --- BI-4 : l'état du rafraîchissement -----------------------------------------


def test_the_refresh_state_is_visible_on_the_dashboard_tab(bi_setup) -> None:
    """`get_latest_refresh_summary` n'avait qu'un appelant — la branche
    « Journal » — alors que sa propre docstring cite le critère mot pour
    mot : « visible sur CHAQUE tableau de bord ». Un chiffre lu sans savoir
    de quand datent les données n'est pas vérifiable.

    **Ce test a d'abord été écrit faux, et la falsification l'a dit.** Il
    assertait `"rafraîchissement" in body` — or la branche `{% else %}` du
    gabarit (« Aucun rafraîchissement n'a encore eu lieu ») contient le même
    mot, et la fixture ne créait aucune exécution : l'assertion était donc
    satisfaite par le message d'ABSENCE, et restait verte après retrait de
    `refresh_summary` du contexte. Même motif que le `href="/crm/"` satisfait
    par le menu latéral (L7). D'où la forme retenue : créer une exécution
    réelle, et n'asserter QUE sur des valeurs que la branche peuplée est
    seule à rendre — les quatre que le critère nomme (dernière exécution,
    durée, volume, échec)."""
    from apps.analytics.tests.factories import AnRefreshRunFactory

    tenant, user, _report = bi_setup
    with use_tenant(tenant.id):
        AnRefreshRunFactory(
            tenant=tenant,
            started_at=dt.datetime(2026, 3, 4, 8, 0, tzinfo=dt.UTC),
            finished_at=dt.datetime(2026, 3, 4, 8, 2, 30, tzinfo=dt.UTC),
            rows_processed=4321,
            reconciliation_ok=False,
        )
    client = _client(tenant, user)

    body = client.get("/bi/?tab=dashboards").content.decode()

    assert "Aucun rafraîchissement" not in body, (
        "La branche « absence » est rendue alors qu'une exécution existe."
    )
    assert "4321" in body, "Le volume (BI-4 « volume ») n'est pas rendu."
    assert "150" in body, "La durée (BI-4 « durée ») n'est pas rendue."
    assert "Écart de réconciliation" in body, "L'échec (BI-4 « échec ») n'est pas signalé."


# --- FOR-7 : l'apport de l'ajustement ------------------------------------------


def test_an_elapsed_forecast_gets_its_error_measured(bi_setup) -> None:
    """`measure_adjustment_contribution` n'était appelée QUE par son test.
    Effet visible : l'onglet qualité filtre sur
    `statistical_error_pct__isnull=False` et restait vide en permanence —
    le critère était infaisable, pas seulement non mesuré."""
    from apps.forecast.models import ForSeriesForecast
    from apps.forecast.services.compute import _reconcile_elapsed_periods
    from apps.forecast.services.history import SeriesHistory
    from apps.forecast.tests.factories import ForSeriesForecastFactory

    tenant, _user, _report = bi_setup
    period = dt.date(2026, 1, 1)
    with use_tenant(tenant.id):
        forecast = ForSeriesForecastFactory(
            tenant=tenant,
            dimension_value="global",
            period=period,
            statistical_value=Decimal("100"),
            adjusted_value=Decimal("110"),
        )
        assert forecast.statistical_error_pct is None

        measured = _reconcile_elapsed_periods(
            tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CANAL,
            dimension_value="global",
            history=SeriesHistory(
                full_periods=[period],
                full_values=[Decimal("120")],
                training_periods=[period],
                training_values=[Decimal("120")],
                excluded_periods=set(),
            ),
        )
        assert measured == 1
        forecast.refresh_from_db()

    # |120 - 100| / 120 = 16,67 % ; |120 - 110| / 120 = 8,33 %.
    assert round(float(forecast.statistical_error_pct), 2) == 16.67
    assert round(float(forecast.adjustment_error_pct), 2) == 8.33


def test_a_period_excluded_from_training_is_not_measured_against(bi_setup) -> None:
    """La falsification, et elle a un sens métier : mesurer la qualité
    d'une prévision contre un réalisé qu'on a soi-même jugé non
    représentatif (valeur aberrante écartée par le diagnostic de série) ne
    dirait rien d'utile."""
    from apps.forecast.models import ForSeriesForecast
    from apps.forecast.services.compute import _reconcile_elapsed_periods
    from apps.forecast.services.history import SeriesHistory
    from apps.forecast.tests.factories import ForSeriesForecastFactory

    tenant, _user, _report = bi_setup
    period = dt.date(2026, 2, 1)
    with use_tenant(tenant.id):
        forecast = ForSeriesForecastFactory(
            tenant=tenant,
            dimension_value="global",
            period=period,
            statistical_value=Decimal("100"),
        )
        measured = _reconcile_elapsed_periods(
            tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CANAL,
            dimension_value="global",
            history=SeriesHistory(
                full_periods=[period],
                full_values=[Decimal("999")],
                training_periods=[],
                training_values=[],
                excluded_periods={period},
            ),
        )
        assert measured == 0
        forecast.refresh_from_db()
    assert forecast.statistical_error_pct is None


# --- FOR-9 : le délai par client ------------------------------------------------


def test_the_cash_projection_uses_each_clients_own_delay_when_it_can(bi_setup) -> None:
    """FOR-9 : « dérivée du comportement de règlement observé PAR CLIENT,
    non d'un délai théorique unique ».

    Le blocage n'était pas la formule mais la DIMENSION LUE : les
    prévisions consommées étaient filtrées sur `DIMENSION_CANAL`, un
    agrégat qui ne porte aucun client — il n'y avait rien à quoi rattacher
    un délai individuel. Le service écrasait donc en moyenne non pondérée
    les délais que `get_partner_payment_behavior` fournit déjà un par un.
    """
    from unittest.mock import patch

    from apps.forecast.models import ForSeriesForecast
    from apps.forecast.services.treasury import project_twelve_month_cash_inflows
    from apps.forecast.tests.factories import ForSeriesForecastFactory

    tenant, _user, _report = bi_setup
    rapide, lent = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    behavior = [
        {"partner_id": rapide, "nom": "Rapide", "avg_delay_days": 5, "sales_count": 10},
        {"partner_id": lent, "nom": "Lent", "avg_delay_days": 90, "sales_count": 10},
    ]

    with use_tenant(tenant.id):
        ForSeriesForecastFactory(
            tenant=tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CLIENT,
            dimension_value=rapide,
            period=dt.date(2026, 1, 1),
            statistical_value=Decimal("1000"),
        )
        ForSeriesForecastFactory(
            tenant=tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CLIENT,
            dimension_value=lent,
            period=dt.date(2026, 1, 1),
            statistical_value=Decimal("1000"),
        )
        with patch(
            "apps.forecast.services.treasury.get_partner_payment_behavior",
            return_value=behavior,
        ):
            result = project_twelve_month_cash_inflows(tenant)

    assert result["assumption_basis"] == "par_client"
    # Les deux ventes du MEME mois tombent dans des mois d'encaissement
    # DIFFERENTS : c'est exactement ce qu'un delai unique ne pouvait pas
    # produire, et c'est la preuve que chaque client porte le sien.
    months = [row["period"] for row in result["monthly_inflows"]]
    assert len(months) == 2
    assert months[0] == dt.date(2026, 1, 1)
    assert months[1] == dt.date(2026, 4, 1)


def test_without_per_client_forecasts_the_delay_is_weighted_not_flat(bi_setup) -> None:
    """La falsification, et le repli assumé : sans prévision par client, un
    délai unique reste inévitable — mais PONDÉRÉ par le poids réel de
    chaque client, jamais une moyenne plate où un client d'une facture pèse
    autant qu'un client de cinq cents. Le résultat dit lequel s'applique.
    """
    from unittest.mock import patch

    from apps.forecast.models import ForSeriesForecast
    from apps.forecast.services.treasury import project_twelve_month_cash_inflows
    from apps.forecast.tests.factories import ForSeriesForecastFactory

    tenant, _user, _report = bi_setup
    behavior = [
        {"partner_id": "a", "nom": "Gros", "avg_delay_days": 10, "sales_count": 90},
        {"partner_id": "b", "nom": "Petit", "avg_delay_days": 100, "sales_count": 10},
    ]
    with use_tenant(tenant.id):
        ForSeriesForecastFactory(
            tenant=tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CANAL,
            dimension_value="global",
            period=dt.date(2026, 1, 1),
        )
        with patch(
            "apps.forecast.services.treasury.get_partner_payment_behavior",
            return_value=behavior,
        ):
            result = project_twelve_month_cash_inflows(tenant)

    assert result["assumption_basis"] == "canal_pondere"
    # Moyenne PONDEREE : (10x90 + 100x10) / 100 = 19 jours.
    # La moyenne plate aurait donne 55 — presque trois fois plus.
    assert result["assumption_avg_delay_days"] == 19


def test_the_screen_says_which_of_the_two_bases_it_used(bi_setup) -> None:
    """`assumption_basis` était calculé et **aucune surface ne le lisait** —
    exactement le motif que ce chantier traque. L'écran affichait « Délai
    moyen de règlement retenu : N jours » à l'identique dans les deux
    régimes : le lecteur ne pouvait pas distinguer « le délai propre à
    chaque client » (le critère tenu) de « une moyenne appliquée à tous »
    (un repli). Un chiffre dont on ignore l'hypothèse n'est pas
    vérifiable."""
    from apps.forecast.models import ForSeriesForecast
    from apps.forecast.tests.factories import ForSeriesForecastFactory

    tenant, user, _report = bi_setup
    with use_tenant(tenant.id):
        ForSeriesForecastFactory(
            tenant=tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CANAL,
            dimension_value="global",
            period=dt.date(2026, 1, 1),
        )
    client = _client(tenant, user)
    body = client.get("/forecast/?tab=tresorerie").content.decode()
    assert "délai unique appliqué à tous les clients" in body

    with use_tenant(tenant.id):
        ForSeriesForecastFactory(
            tenant=tenant,
            dimension_type=ForSeriesForecast.DIMENSION_CLIENT,
            dimension_value="peu-importe",
            period=dt.date(2026, 1, 1),
        )
    body = client.get("/forecast/?tab=tresorerie").content.decode()
    assert "délai propre à chaque client" in body
    assert "délai unique appliqué à tous les clients" not in body


# --- FOR-10 : la prévision publiée comme scénario de référence ------------------


def test_the_published_forecast_reaches_the_simulation_baseline_with_its_version(
    bi_setup,
) -> None:
    """« Prévision publiée disponible comme scénario de référence dans la
    simulation, AVEC SA VERSION ET SA DATE. »

    Le patron existait déjà — dans un autre module : `strategy` importe la
    même façade et conserve version et date dans `source_reference`.
    `simulation/services/baseline.py` n'avait, lui, aucune référence à
    `apps.forecast` : la trésorerie qu'il injectait était la projection
    COMPTABLE à 91 jours, pas une prévision."""
    from unittest.mock import patch

    from apps.simulation.services.baseline import build_baseline

    tenant, user, _report = bi_setup
    publication = {
        "version": 3,
        "published_at": dt.datetime(2026, 2, 1, 8, 0, tzinfo=dt.UTC),
        "period_start": dt.date(2026, 1, 1),
        "period_end": dt.date(2026, 12, 1),
        "snapshot": [
            {
                "dimension_type": "canal",
                "dimension_value": "global",
                "period": dt.date(2026, 3, 1),
                "value": Decimal("5000"),
            }
        ],
    }
    with (
        use_tenant(tenant.id),
        patch(
            "apps.forecast.services.public.get_latest_published_forecast",
            return_value=publication,
        ),
    ):
        baseline = build_baseline(tenant=tenant, user=user)

    injected = baseline.data["forecast_publication"]
    assert injected["version"] == 3
    assert injected["published_at"].startswith("2026-02-01")
    assert injected["entries"][0]["value"] == "5000"


def test_a_baseline_without_any_publication_simply_carries_none(bi_setup) -> None:
    """La falsification : aucune prévision publiée ne doit pas empêcher de
    construire un socle — c'est le cas d'un tenant qui n'utilise pas encore
    le module de prévision."""
    from apps.simulation.services.baseline import build_baseline

    tenant, user, _report = bi_setup
    with use_tenant(tenant.id):
        baseline = build_baseline(tenant=tenant, user=user)
    assert "forecast_publication" not in baseline.data
