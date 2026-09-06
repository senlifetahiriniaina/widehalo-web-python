"""Bloquants (4/4) — RG-ACC-5, volet « proposee ».

La regle, telle que le depot la formule lui-meme
(`apps/accounting/models.py:614`) : « sur un tenant au regime synthetique,
aucune AccTax n'est **proposee ni appliquee** ».

Seul le volet « appliquee » etait tenu, et uniquement par trois surfaces de
LECTURE. L'ecran de parametrage, lui, creait une `AccTax` sur un tenant non
assujetti sans le moindre avertissement, et listait par
`AccTax.objects.filter(...)` direct plutot que par `applicable_taxes()`. Le
modele ne porte la regle qu'en commentaire — ni `clean()`, ni contrainte.

Consequence : un tenant synthetique pouvait se constituer un jeu de taxes
que le produit refuserait ensuite d'appliquer. Une configuration sans effet,
et rien pour le dire."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounting.models import AccTax
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"
URL = "/accounting/config/taxes/"


def _logged_in(tenant: Tenant, email: str) -> Client:
    """Meme forme que `tests/ui/test_accounting_config_screens.py`.

    Volontairement SANS `grant_role` : « admin », « comptable » et
    « direction » sont dans `CORE_MFA_REQUIRED_ROLES`, et un utilisateur
    porteur de l'un d'eux est redirige vers l'enrolement MFA avant
    d'atteindre l'ecran. Un premier jet de ce fichier en donnait un : la
    requete n'arrivait jamais a la vue, aucune taxe n'etait creee, et le
    test du refus passait **pour la mauvaise raison**. C'est le test de
    falsification (« un tenant assujetti cree quand meme ») qui l'a
    revele — un rappel que la moitie qui doit rester verte n'est pas
    decorative."""
    with use_tenant(tenant.id):
        user = User.objects.create_user(email=email, password=PASSWORD)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _post_a_tax(client: Client):
    return client.post(
        URL,
        {"code": "TVA20", "name": "TVA 20%", "type": AccTax.TYPE_SALE, "rate": "20"},
        follow=True,
    )


def test_a_non_liable_tenant_cannot_register_a_tax_by_post() -> None:
    """Le refus est cote POST, jamais seulement dans le gabarit : masquer un
    formulaire n'empeche personne de poster."""
    tenant = Tenant.objects.create(
        code="ACC-B4-SYN",
        name="Synthetique SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC,
    )
    client = _logged_in(tenant, "b4-syn@example.com")

    response = _post_a_tax(client)
    assert response.status_code == 200

    with use_tenant(tenant.id):
        assert not AccTax.objects.filter(tenant=tenant).exists()


def test_the_screen_says_why_rather_than_failing_silently() -> None:
    tenant = Tenant.objects.create(
        code="ACC-B4-DIT",
        name="Synthetique bavarde SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC,
    )
    client = _logged_in(tenant, "b4-dit@example.com")
    body = client.get(URL).content.decode()
    assert "n&#x27;est pas assujetti" in body or "n'est pas assujetti" in body


def test_a_liable_tenant_still_registers_its_taxes() -> None:
    """La falsification. Sans elle, « la garde protege le non-assujetti » et
    « la garde a casse l'ecran pour tout le monde » seraient
    indiscernables."""
    tenant = Tenant.objects.create(
        code="ACC-B4-REEL",
        name="Assujettie SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_REAL_WITH_VAT,
    )
    client = _logged_in(tenant, "b4-reel@example.com")

    response = _post_a_tax(client)
    assert response.status_code == 200

    with use_tenant(tenant.id):
        tax = AccTax.objects.filter(tenant=tenant).first()
    assert tax is not None
    assert tax.code == "TVA20"
