"""PRC1-3 (chantier veille prix fournisseurs Chine/Europe — cf. plan) :
`apps.purchase.services.price_watch`. Le test le plus important de ce
fichier est `test_stub_provider_never_performs_any_network_call` — il
verifie explicitement que `StubPriceSourceProvider`/`get_provider_for_
platform` (sans configuration) n'ouvrent RIGOUREUSEMENT AUCUN socket
reseau, meme si le code appelant tentait d'en ouvrir un (patch de
`socket.socket` qui echoue le test si invoque)."""

from __future__ import annotations

import socket
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PrcPriceSnapshot, PrcPriceWatchTarget
from apps.purchase.services.price_watch import (
    GenericHttpPriceSourceProvider,
    PriceQuote,
    StubPriceSourceProvider,
    check_price_watch_target,
    create_price_watch_target,
    get_provider_for_platform,
    run_price_watch_checks,
)
from apps.purchase.tests.factories import PrcPriceWatchTargetFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="PRC-T", name="Price Watch Tenant")


# ---------------------------------------------------------------------------
# Reserve de securite : stub actif par defaut, aucun appel reseau
# ---------------------------------------------------------------------------


def test_get_provider_for_platform_returns_stub_by_default(tenant) -> None:
    """Aucune entree dans `settings.PRICE_WATCH_PROVIDERS` (defaut du
    projet, `{}`) : TOUTE plateforme resout vers le stub."""
    for platform_code, _label in PrcPriceWatchTarget.PLATFORM_CHOICES:
        assert isinstance(get_provider_for_platform(platform_code), StubPriceSourceProvider)


@override_settings(PRICE_WATCH_PROVIDERS={"alibaba": {"base_url": "https://example.test"}})
def test_get_provider_for_platform_stays_stub_when_config_incomplete() -> None:
    """`api_key` manquant : reste sur le stub, jamais un connecteur reel a
    moitie configure."""
    assert isinstance(
        get_provider_for_platform(PrcPriceWatchTarget.PLATFORM_ALIBABA), StubPriceSourceProvider
    )


@override_settings(
    PRICE_WATCH_PROVIDERS={"alibaba": {"base_url": "https://example.test", "api_key": "secret"}}
)
def test_get_provider_for_platform_switches_to_real_connector_when_fully_configured() -> None:
    provider = get_provider_for_platform(PrcPriceWatchTarget.PLATFORM_ALIBABA)
    assert isinstance(provider, GenericHttpPriceSourceProvider)
    # Une autre plateforme non configuree reste sur le stub.
    assert isinstance(
        get_provider_for_platform(PrcPriceWatchTarget.PLATFORM_EUROPAGES),
        StubPriceSourceProvider,
    )


def test_stub_provider_never_performs_any_network_call(tenant) -> None:
    """Verification explicite demandee par le cadrage du chantier :
    `StubPriceSourceProvider.fetch_price` ne doit ouvrir AUCUN socket
    reseau. On patche `socket.socket` pour faire echouer le test si
    quoi que ce soit tentait d'en ouvrir un."""

    def _forbidden_socket(*args, **kwargs):
        raise AssertionError(
            "Un socket reseau a ete ouvert par le stub — violation de la reserve "
            "de securite/legalite (aucun appel reseau sans connecteur configure)."
        )

    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)

    original_socket = socket.socket
    socket.socket = _forbidden_socket  # type: ignore[assignment]
    try:
        quote = StubPriceSourceProvider().fetch_price(target)
    finally:
        socket.socket = original_socket  # type: ignore[assignment]

    assert quote.is_stub is True
    assert quote.price is None
    assert "non configure" in quote.note.lower()


def test_check_price_watch_target_creates_stub_snapshot(tenant) -> None:
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)
        snapshot = check_price_watch_target(target)

        assert snapshot.is_stub is True
        assert snapshot.observed_price is None
        assert snapshot.target_id == target.id
        assert PrcPriceSnapshot.objects.filter(target=target).count() == 1


# ---------------------------------------------------------------------------
# create_price_watch_target — invariant XOR reference produit
# ---------------------------------------------------------------------------


def test_create_price_watch_target_requires_exactly_one_product_reference(tenant) -> None:
    with use_tenant(tenant.id):
        with pytest.raises(ValueError):
            create_price_watch_target(
                tenant=tenant,
                platform_code=PrcPriceWatchTarget.PLATFORM_ALIBABA,
                search_query_or_url="tissu coton",
            )
        with pytest.raises(ValueError):
            create_price_watch_target(
                tenant=tenant,
                platform_code=PrcPriceWatchTarget.PLATFORM_ALIBABA,
                search_query_or_url="tissu coton",
                material_reference_id=uuid.uuid4(),
                variant_id=uuid.uuid4(),
            )


def test_create_price_watch_target_with_variant_id_succeeds(tenant) -> None:
    with use_tenant(tenant.id):
        target = create_price_watch_target(
            tenant=tenant,
            platform_code=PrcPriceWatchTarget.PLATFORM_1688,
            search_query_or_url="https://1688.com/search?q=tissu",
            variant_id=uuid.uuid4(),
        )
        assert target.material_reference_id is None
        assert target.variant_id is not None


def test_create_price_watch_target_with_material_reference_id_succeeds(tenant) -> None:
    with use_tenant(tenant.id):
        target = create_price_watch_target(
            tenant=tenant,
            platform_code=PrcPriceWatchTarget.PLATFORM_EUROPAGES,
            search_query_or_url="tissu coton bio",
            material_reference_id=uuid.uuid4(),
        )
        assert target.variant_id is None
        assert target.material_reference_id is not None


# ---------------------------------------------------------------------------
# run_price_watch_checks — cadence, ecart, notification
# ---------------------------------------------------------------------------


def test_run_price_watch_checks_skips_target_not_yet_due(tenant) -> None:
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(
            tenant=tenant, frequency=PrcPriceWatchTarget.FREQUENCY_MONTHLY
        )
        PrcPriceSnapshot.objects.create(
            tenant=tenant, target=target, observed_at=timezone.now(), is_stub=True
        )
        assert run_price_watch_checks(tenant) == []


def test_run_price_watch_checks_runs_target_never_checked_before(tenant) -> None:
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)
        results = run_price_watch_checks(tenant)

        assert len(results) == 1
        assert results[0]["is_stub"] is True
        assert PrcPriceSnapshot.objects.filter(target=target).count() == 1


def test_run_price_watch_checks_runs_target_past_due_interval(tenant) -> None:
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(
            tenant=tenant, frequency=PrcPriceWatchTarget.FREQUENCY_MONTHLY
        )
        PrcPriceSnapshot.objects.create(
            tenant=tenant,
            target=target,
            observed_at=timezone.now() - timedelta(days=45),
            is_stub=True,
        )
        results = run_price_watch_checks(tenant)
        assert len(results) == 1
        assert PrcPriceSnapshot.objects.filter(target=target).count() == 2


def test_run_price_watch_checks_ignores_inactive_targets(tenant) -> None:
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant, is_active=False)
        assert run_price_watch_checks(tenant) == []
        assert PrcPriceSnapshot.objects.filter(target=target).count() == 0


@override_settings(
    PRICE_WATCH_PROVIDERS={"alibaba": {"base_url": "https://example.test", "api_key": "secret"}}
)
def test_run_price_watch_checks_alerts_acheteur_role_past_deviation_threshold(
    monkeypatch, tenant
) -> None:
    """Ecart > seuil (15%) entre le releve PRECEDENT (semence manuellement,
    simulant un releve reel deja en base) et le NOUVEAU releve (via un
    connecteur configure a des fins de test, jamais le stub qui ne renvoie
    jamais de prix) : `notify_role("acheteur", ...)` est appele — verifie
    via de vraies `Notification` creees pour un utilisateur du role
    `acheteur`."""
    user = User.objects.create_user(email="acheteur-prc@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="acheteur")
    user.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant)

    monkeypatch.setattr(
        GenericHttpPriceSourceProvider,
        "fetch_price",
        lambda self, target: PriceQuote(
            price=Decimal(1300), currency="USD", is_stub=False, note="second releve, +30%"
        ),
    )

    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(
            tenant=tenant,
            platform_code=PrcPriceWatchTarget.PLATFORM_ALIBABA,
            currency="USD",
        )
        PrcPriceSnapshot.objects.create(
            tenant=tenant,
            target=target,
            observed_price=Decimal(1000),
            observed_at=timezone.now() - timedelta(days=45),
            is_stub=False,
        )
        results = run_price_watch_checks(tenant)

        assert results[0]["deviation_pct"] == Decimal("30.00")

    assert Notification.objects.filter(
        user=user, notification_type="purchase.price_watch_deviation"
    ).exists()


@override_settings(
    PRICE_WATCH_PROVIDERS={"alibaba": {"base_url": "https://example.test", "api_key": "secret"}}
)
def test_run_price_watch_checks_does_not_alert_below_threshold(monkeypatch, tenant) -> None:
    user = User.objects.create_user(
        email="acheteur-prc-2@example.com", password="Str0ngPassw0rd!23"
    )
    group, _ = Group.objects.get_or_create(name="acheteur")
    user.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant)

    monkeypatch.setattr(
        GenericHttpPriceSourceProvider,
        "fetch_price",
        lambda self, target: PriceQuote(
            price=Decimal(1050), currency="USD", is_stub=False, note=""
        ),  # +5% vs le releve precedent
    )

    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(
            tenant=tenant, platform_code=PrcPriceWatchTarget.PLATFORM_ALIBABA, currency="USD"
        )
        PrcPriceSnapshot.objects.create(
            tenant=tenant,
            target=target,
            observed_price=Decimal(1000),
            observed_at=timezone.now() - timedelta(days=45),
            is_stub=False,
        )
        results = run_price_watch_checks(tenant)
        assert results[0]["deviation_pct"] == Decimal("5.00")

    assert not Notification.objects.filter(
        user=user, notification_type="purchase.price_watch_deviation"
    ).exists()
