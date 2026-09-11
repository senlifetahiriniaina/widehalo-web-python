"""E-3 et E-4 — ce que les deux modules affichent, et ce qu'ils produisent.

Trois fonctions publiques de ces modules etaient livrees, testees, correctes
— et **sans aucun appelant de production**. Une table structurellement vide
et un ecran qui enregistre une periodicite sans jamais produire de tournee :
le motif « rien de decoratif », vu pour la treizieme fois.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from html import unescape

import pytest
from apps.accounting.models import AccAggregatorPayout
from apps.accounting.services.payment_providers import PROVIDER_AGGREGATOR
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.logistics.models import LogDriver, LogTrip, LogTripTemplate, LogVehicle
from apps.logistics.services.trips import create_trip_template
from django.test import Client
from django_otp.oath import totp

pytestmark = pytest.mark.django_db


def _connecte(tenant: Tenant, email: str, role: str) -> Client:
    """**`force_login` ne suffit pas pour un role a MFA obligatoire.**

    `admin`, `direction`, `comptable` et `rh` sont dans
    `CORE_MFA_REQUIRED_ROLES` : le middleware renvoie vers `/mfa/` et le
    POST n'atteint jamais la vue. La premiere version de ces tests
    assertait `status_code == 302` — vrai pour une redirection MFA comme
    pour une redirection de succes — et passait donc **pour la mauvaise
    raison**, sans rien ecrire en base. Seule l'assertion de relecture l'a
    demasque. Le harnais enrole donc lui-meme le device TOTP, comme le fait
    `apps/flows/tests/test_t8_fragment_echanges.py`."""
    with use_tenant(tenant.id):
        user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
        grant_role(user, role)
        UserTenantMembership.objects.get_or_create(user=user, tenant=tenant)
    client = Client()
    reponse = client.post("/login/", {"email": email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302, reponse.content
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    reponse = client.post("/mfa/", {"token": str(totp(device.bin_key)).zfill(6)})
    assert reponse.status_code == 302, reponse.content
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


@pytest.fixture
def compta():
    tenant = Tenant.objects.create(code="E3", name="E3 Compta")
    return _connecte(tenant, "e3@example.com", "admin"), tenant


@pytest.fixture
def logistique():
    tenant = Tenant.objects.create(code="E4", name="E4 Logistique")
    client = _connecte(tenant, "e4@example.com", "admin")
    with use_tenant(tenant.id):
        vehicule = LogVehicle.objects.create(
            tenant=tenant, plate_number="TAA-001", type=LogVehicle.TYPE_TRUCK
        )
        chauffeur = LogDriver.objects.create(tenant=tenant, name="Rakoto", phone="+261")
    return client, tenant, vehicule, chauffeur


# --- E-3 : le versement groupe peut enfin exister -------------------------


def test_un_versement_annonce_apparait_dans_la_table_a_rapprocher(compta) -> None:
    """**`announce_payout` n'avait aucun appelant.** Elle est le seul
    createur d'`AccAggregatorPayout` : la table « Versements groupes a
    rapprocher » et son bouton « Rapprocher le lot » etaient structurellement
    inaccessibles."""
    client, tenant = compta
    reponse = client.post(
        "/accounting/payments/payouts/announce/",
        {
            "provider_code": PROVIDER_AGGREGATOR,
            "external_reference": "REL-2026-09-11",
            "payout_date": str(dt.date.today()),
            "gross_amount": "1000000",
            "fee_amount": "15000",
            "net_amount": "985000",
        },
    )
    assert reponse.status_code == 302

    with use_tenant(tenant.id):
        versement = AccAggregatorPayout.objects.get(external_reference="REL-2026-09-11")
    assert versement.net_amount == Decimal("985000")

    contenu = client.get("/accounting/payments/notifications/?state=toutes").content.decode()
    assert "REL-2026-09-11" in contenu
    # Les montants s'affichent comme partout : separateur de milliers et
    # unite, jamais un Decimal brut.
    assert "985 000 Ar" in contenu, "le net recu est rendu en chiffres bruts"
    # Et l'etat par son LIBELLE, jamais par son code : la colonne rendait
    # `{{ payout.state }}`, c'est-a-dire « annonce ».
    # Django echappe l'apostrophe en `&#x27;` : comparer au texte brut
    # ferait echouer le test sur une difference d'encodage, pas de fond.
    assert "Annoncé par l'agrégateur" in unescape(contenu), (
        "l'etat du versement est rendu en code technique"
    )


def test_un_versement_sans_reference_est_refuse_sans_rien_ecrire(compta) -> None:
    """Le service refuse deja ; l'ecran ne doit pas transformer ce refus en
    500 ni en creation silencieuse."""
    client, tenant = compta
    with use_tenant(tenant.id):
        avant = AccAggregatorPayout.objects.count()
    reponse = client.post(
        "/accounting/payments/payouts/announce/",
        {
            "provider_code": PROVIDER_AGGREGATOR,
            "external_reference": "  ",
            "payout_date": str(dt.date.today()),
            "gross_amount": "1000",
            "fee_amount": "0",
            "net_amount": "1000",
        },
    )
    assert reponse.status_code == 302
    with use_tenant(tenant.id):
        assert AccAggregatorPayout.objects.count() == avant


# --- E-4 : un gabarit produit enfin une tournee ---------------------------


def test_le_bouton_genere_les_tournees_dues(logistique) -> None:
    """**`generate_due_trip` n'avait aucun appelant de production.** L'ecran
    enregistrait une periodicite et ne produisait jamais de trajet."""
    client, tenant, vehicule, chauffeur = logistique
    with use_tenant(tenant.id):
        create_trip_template(
            tenant,
            name="Tournee Nord",
            vehicle=vehicule,
            driver=chauffeur,
            interval=LogTripTemplate.INTERVAL_WEEKLY,
            stops_data=[{"address": "Tamatave"}],
            start_date=dt.date.today() - dt.timedelta(days=1),
        )
        avant = LogTrip.objects.count()

    reponse = client.post("/logistics/trip-templates/", {"action": "generate_due"})
    assert reponse.status_code == 302

    with use_tenant(tenant.id):
        assert LogTrip.objects.count() == avant + 1
        tournee = LogTrip.objects.order_by("-created_at").first()
        assert tournee is not None
        # LOG-REC1 : TOUJOURS en `planned`, jamais demarree d'office.
        assert tournee.status == LogTrip.STATUS_PLANNED


def test_generer_deux_fois_le_meme_jour_ne_duplique_pas(logistique) -> None:
    """`generate_due_trip` avance `next_run` et rend `None` ensuite : le
    bouton est sans effet le reste de la journee. Sans cette propriete, un
    double-clic engagerait deux fois le meme vehicule."""
    client, tenant, vehicule, chauffeur = logistique
    with use_tenant(tenant.id):
        create_trip_template(
            tenant,
            name="Tournee Sud",
            vehicle=vehicule,
            driver=chauffeur,
            interval=LogTripTemplate.INTERVAL_WEEKLY,
            stops_data=[{"address": "Fianarantsoa"}],
            start_date=dt.date.today(),
        )

    client.post("/logistics/trip-templates/", {"action": "generate_due"})
    with use_tenant(tenant.id):
        apres_un = LogTrip.objects.count()
    client.post("/logistics/trip-templates/", {"action": "generate_due"})
    with use_tenant(tenant.id):
        assert LogTrip.objects.count() == apres_un


def test_les_etats_des_expeditions_sont_accentues() -> None:
    """Les 54 libelles de `logistics` sont passes par les trois etages :
    l'instrument mecanique, les ambigus tranches a la main, et les participes
    qu'aspell ne peut pas voir — « Cloture », « Dedouane », « Planifie »."""
    from apps.logistics.models import LogShipment

    etats = {str(libelle) for _code, libelle in LogShipment.STATE_CHOICES}
    assert "Clôturée" in etats and "Cloturee" not in etats
    assert "Livrée" in etats and "Livree" not in etats
    statuts = {str(libelle) for _code, libelle in LogTrip.STATUS_CHOICES}
    assert "Planifié" in statuts and "Planifie" not in statuts
