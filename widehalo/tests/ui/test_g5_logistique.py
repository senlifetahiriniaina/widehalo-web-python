"""G-5 — la logistique : ce que la mesure a trouvé, et ce qu'elle a démenti.

**Le plan annonçait cinq trous ; la mesure en a confirmé trois et démenti
deux.** `add_vehicle_document` et `record_vehicle_cost` ont déjà leur écran
depuis LOG7 (la fiche du véhicule), et `add_shipment_leg` aussi (la fiche
de l'expédition). Les écrire à nouveau aurait dupliqué du travail livré.

Restent trois chaînes réellement hors de portée, vérifiées une à une :

- `record_trip_fuel_cost` — **aucun appelant du tout** : ni vue, ni API, ni
  commande. Le carburant d'une tournée était écrit, testé, injoignable.
- `compute_packaging_plan` et `suggest_stop_order`/`reorder_stops` — API
  seulement : un exploitant devant un navigateur ne pouvait ni savoir
  combien de colis prévoir, ni faire proposer un ordre de visite.
- `upcoming_document_alerts` — appelée par la maintenance nocturne, qui
  NOTIFIE et ne montre rien : aucun écran ne listait les échéances.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from apps.logistics.models import (
    LogPackagingPlan,
    LogPackagingType,
    LogTripStop,
    LogVehicle,
    LogVehicleCost,
    LogVehicleDocument,
)
from apps.logistics.services.shipments import create_shipment
from apps.logistics.services.trips import create_trip
from apps.logistics.services.vehicles import add_vehicle_document, create_driver, create_vehicle
from django.test import Client

pytestmark = pytest.mark.django_db


def _connecte(user: User, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


@pytest.fixture
def societe():
    tenant = Tenant.objects.create(code="G5", name="Societe logistique")
    user = User.objects.create_user(email="g5@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "logistics")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    with use_tenant(tenant.id):
        vehicule = create_vehicle(tenant, plate_number="1234 TBA", type=LogVehicle.TYPE_TRUCK)
        chauffeur = create_driver(tenant, name="Randria Jean")
        trajet = create_trip(
            tenant,
            vehicle=vehicule,
            driver=chauffeur,
            date=dt.date(2026, 3, 2),
            stops=[
                {
                    "address": "Antananarivo",
                    "latitude": Decimal("-18.90"),
                    "longitude": Decimal("47.52"),
                },
                {
                    "address": "Toamasina",
                    "latitude": Decimal("-18.15"),
                    "longitude": Decimal("49.40"),
                },
                {
                    "address": "Ambatondrazaka",
                    "latitude": Decimal("-17.83"),
                    "longitude": Decimal("48.42"),
                },
            ],
        )
        expedition = create_shipment(tenant, origin="Toamasina", destination="Antananarivo")
        contenant = LogPackagingType.objects.create(
            tenant=tenant,
            code="CART",
            name="Carton standard",
            tare_weight_kg=Decimal("1.200"),
            volume_m3=Decimal("0.1200"),
        )
    return {
        "tenant": tenant,
        "user": user,
        "client": _connecte(user, tenant),
        "vehicule": vehicule,
        "trajet": trajet,
        "expedition": expedition,
        "contenant": contenant,
    }


def test_un_plein_de_carburant_senregistre_depuis_la_fiche_de_trajet(societe) -> None:
    """`record_trip_fuel_cost` n'avait aucun appelant — nulle part."""
    reponse = societe["client"].post(
        f"/logistics/trips/{societe['trajet'].id}/",
        {"action": "record_fuel", "amount_mga": "85000", "note": "Plein Toamasina"},
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        cout = LogVehicleCost.objects.filter(vehicle=societe["vehicule"]).first()
        assert cout is not None, "Le plein n'a rien écrit."
        assert cout.cost_type == LogVehicleCost.TYPE_FUEL
        assert cout.amount_mga == Decimal("85000.0000")
        assert cout.note == "Plein Toamasina"
        # Le coût est rattaché au VÉHICULE du trajet, pas à une entité
        # dédiée : il doit donc se lire sur sa fiche.
        assert cout.date == societe["trajet"].date

    fiche = societe["client"].get(f"/logistics/vehicles/{societe['vehicule'].id}/")
    assert "Plein Toamasina" in fiche.content.decode()


def test_lordre_des_arrets_se_propose_avant_de_sappliquer(societe) -> None:
    """La séparation vient du service, et elle est juste : un ordre de
    tournée imposé sans relecture serait une décision d'exploitation prise
    par un algorithme."""
    trajet = societe["trajet"]
    with use_tenant(societe["tenant"].id):
        avant = [stop.address for stop in trajet.stops.order_by("sequence")]
    assert avant == ["Antananarivo", "Toamasina", "Ambatondrazaka"]

    propose = societe["client"].get(f"/logistics/trips/{trajet.id}/?suggest=1")
    assert propose.status_code == 200
    assert "Ordre proposé" in propose.content.decode()

    with use_tenant(societe["tenant"].id):
        # Proposer ne change rien : c'est ce que la fonction pure garantit.
        toujours = [stop.address for stop in trajet.stops.order_by("sequence")]
    assert toujours == avant

    with use_tenant(societe["tenant"].id):
        ids_par_adresse = {
            stop.address: str(stop.id) for stop in LogTripStop.objects.filter(trip=trajet)
        }
    nouvel_ordre = [
        ids_par_adresse["Toamasina"],
        ids_par_adresse["Ambatondrazaka"],
        ids_par_adresse["Antananarivo"],
    ]
    applique = societe["client"].post(
        f"/logistics/trips/{trajet.id}/",
        {"action": "reorder", "stop_ids": nouvel_ordre},
    )
    assert applique.status_code == 302, applique.content

    with use_tenant(societe["tenant"].id):
        apres = [stop.address for stop in trajet.stops.order_by("sequence")]
    assert apres == ["Toamasina", "Ambatondrazaka", "Antananarivo"]


def test_un_ordre_incomplet_est_refuse_et_lecran_le_dit(societe) -> None:
    trajet = societe["trajet"]
    with use_tenant(societe["tenant"].id):
        un_seul = [str(LogTripStop.objects.filter(trip=trajet).first().id)]

    reponse = societe["client"].post(
        f"/logistics/trips/{trajet.id}/", {"action": "reorder", "stop_ids": un_seul}
    )
    assert reponse.status_code == 200
    assert "exactement les arrêts existants" in reponse.content.decode()


def test_les_echeances_de_documents_ont_enfin_un_ecran(societe) -> None:
    with use_tenant(societe["tenant"].id):
        add_vehicle_document(
            societe["vehicule"],
            doc_type=LogVehicleDocument.TYPE_INSURANCE,
            reference="ASS-2026-77",
            issue_date=dt.date.today() - dt.timedelta(days=300),
            expiry_date=dt.date.today() + dt.timedelta(days=10),
        )

    contenu = societe["client"].get("/logistics/vehicles/document-alerts/").content.decode()
    assert "ASS-2026-77" in contenu
    assert "1234 TBA" in contenu
    assert "Assurance" in contenu


def test_signaler_une_echeance_ne_la_repropose_plus(societe) -> None:
    """`notify_document_alert` marque le document et ne le renvoie jamais
    deux fois : l'écran doit s'aligner sur cette règle, sans quoi
    l'exploitant resignalerait sans fin la même échéance."""
    with use_tenant(societe["tenant"].id):
        document = add_vehicle_document(
            societe["vehicule"],
            doc_type=LogVehicleDocument.TYPE_TECHNICAL_INSPECTION,
            reference="VT-2026-01",
            expiry_date=dt.date.today() + dt.timedelta(days=5),
        )

    reponse = societe["client"].post(
        "/logistics/vehicles/document-alerts/", {"document_id": str(document.id)}
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        document.refresh_from_db()
        assert document.notified_at is not None

    contenu = societe["client"].get("/logistics/vehicles/document-alerts/").content.decode()
    assert "VT-2026-01" not in contenu
    assert "Aucune échéance dans cet horizon" in contenu


def test_le_plan_de_conditionnement_se_calcule_depuis_lexpedition(societe) -> None:
    """`compute_packaging_plan` n'était demandable que par l'API."""
    from apps.catalog.tests.factories import PackagingFactory, ProductVariantFactory

    with use_tenant(societe["tenant"].id):
        variante = ProductVariantFactory(tenant=societe["tenant"], reference="ART-001")
        variante.template.is_sellable = True
        variante.template.save(update_fields=["is_sellable"])
        # `get_variant_packaging` doit rendre un conditionnement, sinon le
        # service refuse — et il a raison : un colis « à l'unité » supposé
        # en silence donnerait un nombre de colis faux.
        PackagingFactory(tenant=societe["tenant"], variant=variante, unit_count=12)

    reponse = societe["client"].post(
        f"/logistics/shipments/{societe['expedition'].id}/",
        {
            "action": "compute_packaging",
            "packaging_type_id": str(societe["contenant"].id),
            "variant_id": str(variante.id),
            "qty": "100",
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        plan = LogPackagingPlan.objects.first()
        assert plan is not None, "Aucun plan de conditionnement n'a été calculé."
        ligne = plan.lines.first()
        assert ligne is not None
        # 100 unités par lots de 12 : neuf colis, le dernier incomplet.
        assert ligne.qty_packages == 9

    contenu = (
        societe["client"].get(f"/logistics/shipments/{societe['expedition'].id}/").content.decode()
    )
    assert "Carton standard" in contenu


def test_un_role_en_lecture_seule_ne_peut_ni_reordonner_ni_signaler(societe) -> None:
    tenant = societe["tenant"]
    lecteur = User.objects.create_user(email="g5-lecture@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    UserTenantMembership.objects.get_or_create(
        user=lecteur, tenant=tenant, defaults={"is_default": True}
    )
    session = _connecte(lecteur, tenant)

    # `controleur_gestion` n'a aucun droit sur `logistics` : la lecture
    # elle-meme est refusee, et c'est la politique de la matrice.
    assert session.get("/logistics/vehicles/document-alerts/").status_code == 403
    assert (
        session.post(
            "/logistics/vehicles/document-alerts/",
            {"document_id": "00000000-0000-0000-0000-000000000000"},
        ).status_code
        == 403
    )


def test_le_magasinier_voit_les_echeances_de_documents(societe) -> None:
    """La matrice donne `logistics` au magasinier : l'écran neuf doit lui
    être ouvert, sans quoi il aurait un droit sans surface."""
    tenant = societe["tenant"]
    magasinier = User.objects.create_user(
        email="g5-magasinier@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(magasinier, "magasinier")
    UserTenantMembership.objects.get_or_create(
        user=magasinier, tenant=tenant, defaults={"is_default": True}
    )
    reponse = _connecte(magasinier, tenant).get("/logistics/vehicles/document-alerts/")
    assert reponse.status_code == 200
    assert "Échéances de documents de véhicule" in reponse.content.decode()


def test_lecran_des_echeances_est_atteignable_depuis_la_liste_des_vehicules(societe) -> None:
    contenu = societe["client"].get("/logistics/").content.decode()
    assert "/logistics/vehicles/document-alerts/" in contenu
