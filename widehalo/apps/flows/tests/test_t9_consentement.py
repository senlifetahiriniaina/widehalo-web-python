"""T9 (CON-2, §9.1) — le consentement de sortie, et la garde d'activation.

**Le critère** : « L'activation d'un connecteur exige un consentement
affichant catégories de données, tiers, pays et durée de conservation
connue ; la décision est journalisée avec son auteur. »

**Ce que la mesure disait avant d'écrire.** `FlwConnector` ne portait ni
pays d'établissement, ni durée de conservation, ni régime tarifaire : un
écran de consentement n'aurait eu que le nom du connecteur à afficher, et
les trois autres informations auraient été **rédigées à la main** — ce que
le §10.2 interdit nommément, « sinon il devient faux à la première
évolution ».

**Et `activate_link` est le seul chemin d'activation du dépôt.** Les deux
refus — consentement, puis plafond pour le régime à l'usage — s'y posent
donc une fois. Une garde posée sur un écran se contournerait en appelant
cette fonction ; deux gardes à deux endroits divergeraient au premier
correctif.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.outbound_schemas import CATEGORY_COMMERCIAL_DOCUMENT
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwConsent, FlwLink
from apps.flows.pricing_regimes import REGIME_INCLUDED, REGIME_USAGE
from apps.flows.services.consent import (
    consent_covers_current_scope,
    declared_categories,
    describe_consent,
    record_consent,
)
from apps.flows.services.public import activate_link
from apps.flows.tests.factories import (
    FlwConnectorFactory,
    FlwLinkFactory,
    FlwMappingFactory,
)

pytestmark = pytest.mark.django_db

#: Écrit ici, jamais importé du module qu'il surveille : le libellé d'une
#: catégorie §9.2 doit rester celui du cahier.
DOCUMENT_COMMERCIAL = "sales.SalesOrder"


@pytest.fixture
def exploitant() -> User:
    return User.objects.create_user(
        email="exploitant-con2@example.com", password="Str0ngPassw0rd!23"
    )


@pytest.fixture
def liaison_a_l_usage():
    tenant = Tenant.objects.create(code="T9-CON2", name="Consentement de sortie")
    with use_tenant(tenant.id):
        connecteur = FlwConnectorFactory(
            tenant=tenant,
            code="mvola",
            name="MVola",
            country_code="MG",
            pricing_regime=REGIME_USAGE,
            retention_days=90,
        )
        lien = FlwLinkFactory(tenant=tenant, connector=connecteur, state=FlwLink.STATE_DRAFT)
        FlwMappingFactory(tenant=tenant, link=lien, document_type=DOCUMENT_COMMERCIAL)
    return tenant, lien


# --- Ce que l'écran doit afficher AVANT validation ----------------------------


def test_the_four_informations_of_the_consent_screen_are_derived(liaison_a_l_usage) -> None:
    """**§9.1, les quatre informations, mot pour mot** : « quelles catégories
    de données sortiront, vers quel tiers, dans quel pays, pour quelle durée
    de conservation connue »."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        description = describe_consent(lien)

    assert description["third_party"] == "MVola"
    assert description["country_code"] == "MG"
    assert description["retention_days"] == 90
    assert [c["code"] for c in description["categories"]] == [CATEGORY_COMMERCIAL_DOCUMENT]
    assert description["categories"][0]["label"]
    assert description["categories"][0]["rule"], (
        "La règle §9.2 doit accompagner la catégorie : « sortie autorisée » et "
        "« interdiction absolue » ne se consentent pas de la même façon."
    )


def test_the_categories_are_read_from_the_mappings_never_typed(liaison_a_l_usage) -> None:
    """§10.2 : « le texte des catégories est généré depuis la déclaration de
    l'adaptateur, jamais rédigé à la main — sinon il devient faux à la
    première évolution ».

    Ajouter une correspondance change donc ce que l'écran annonce, sans que
    personne n'ait à mettre un texte à jour."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        assert declared_categories(lien) == [CATEGORY_COMMERCIAL_DOCUMENT]

        FlwMappingFactory(tenant=tenant, link=lien, document_type="crm.CrmLead")
        codes = declared_categories(lien)

    assert len(codes) == 2, (
        "Une correspondance ajoutée n'a pas changé les catégories annoncées : "
        "l'écran afficherait un périmètre périmé."
    )


def test_a_link_without_any_mapping_declares_nothing(liaison_a_l_usage) -> None:
    """C'est l'état d'une liaison qu'on vient de créer. Dire « aucune
    catégorie » est plus vrai qu'une liste rassurante : il n'y a rien à
    consentir tant qu'aucune correspondance n'existe."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        lien.mappings.all().delete()
        assert declared_categories(lien) == []


# --- La garde d'activation ----------------------------------------------------


def test_activation_is_refused_without_a_consent(liaison_a_l_usage) -> None:
    """**LE critère.** « Aucun connecteur n'est actif par défaut. Son
    activation est une décision explicite » (§9.1)."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id), pytest.raises(ValidationError) as refus:
        activate_link(tenant, connector_code="mvola")

    assert "consentement" in " ".join(refus.value.messages).lower()
    lien.refresh_from_db()
    assert lien.state == FlwLink.STATE_DRAFT


def test_activation_is_refused_without_a_cap_on_a_usage_connector(
    liaison_a_l_usage, exploitant
) -> None:
    """§15.2, mot pour mot : « Plafond obligatoire avant activation. Aucun
    connecteur du régime à l'usage ne peut être activé sans qu'un plafond ne
    soit défini. »"""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        record_consent(lien, granted_by=exploitant)
        with pytest.raises(ValidationError) as refus:
            activate_link(tenant, connector_code="mvola")

    assert "plafond" in " ".join(refus.value.messages).lower()


def test_a_connector_outside_the_usage_regime_needs_no_cap(liaison_a_l_usage, exploitant) -> None:
    """Le plafond est obligatoire **pour le régime à l'usage**, pas pour
    tous : l'imposer à un connecteur gratuit ferait d'une protection contre
    la facture surprise une formalité sans objet."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        lien.connector.pricing_regime = REGIME_INCLUDED
        lien.connector.save(update_fields=["pricing_regime"])
        record_consent(lien, granted_by=exploitant)

        assert activate_link(tenant, connector_code="mvola") is True
        lien.refresh_from_db()

    assert lien.state == FlwLink.STATE_ACTIVE


def test_activation_is_refused_when_the_regime_is_not_declared(
    liaison_a_l_usage, exploitant
) -> None:
    """Un régime non déclaré n'est pas un régime par défaut. Le combler par
    « socle inclus » exempterait silencieusement du plafond un connecteur
    qui coûte à chaque appel."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        lien.connector.pricing_regime = ""
        lien.connector.save(update_fields=["pricing_regime"])
        record_consent(lien, granted_by=exploitant)

        with pytest.raises(ValidationError) as refus:
            activate_link(tenant, connector_code="mvola")

    assert "regime" in " ".join(refus.value.messages).lower().replace("é", "e")


def test_a_consented_and_capped_link_activates(liaison_a_l_usage, exploitant) -> None:
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        record_consent(lien, granted_by=exploitant)
        lien.monthly_cost_cap_ariary = Decimal("50000.00")
        lien.save(update_fields=["monthly_cost_cap_ariary"])

        assert activate_link(tenant, connector_code="mvola") is True
        lien.refresh_from_db()

    assert lien.state == FlwLink.STATE_ACTIVE


# --- Ce que la décision conserve ---------------------------------------------


def test_the_decision_is_recorded_with_its_author(liaison_a_l_usage, exploitant) -> None:
    """« La décision est journalisée **avec son auteur** » — et elle doit
    être RELUE : par l'exploitant qui veut savoir ce qu'il a accepté, par la
    révocation qui doit dire ce qu'elle coupe, et par le client qui part
    avec son export de garantie de sortie."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        consentement = record_consent(lien, granted_by=exploitant)

        relu = FlwConsent.objects.get(id=consentement.id)

    assert relu.granted_by_id == exploitant.id
    assert relu.granted_at is not None
    assert relu.third_party == "MVola"
    assert relu.country_code == "MG"
    assert relu.retention_days == 90
    assert relu.categories == [CATEGORY_COMMERCIAL_DOCUMENT]


def test_a_widened_scope_is_no_longer_covered_by_yesterdays_consent(
    liaison_a_l_usage, exploitant
) -> None:
    """**Le point qui a demandé le plus de réflexion.**

    Ce qui a été consenti ne doit pas changer sous les pieds de celui qui a
    consenti. Si une correspondance ajoutée demain fait sortir une catégorie
    de plus, le consentement d'hier ne la couvre pas — et c'est l'écart
    entre le gel et la dérivation courante qui doit conduire à reconsentir.

    Dériver à l'affichage (§10.2) et geler à la preuve ne s'opposent donc
    pas : la dérivation sert l'ÉCRAN, le gel sert la PREUVE."""
    tenant, lien = liaison_a_l_usage
    with use_tenant(tenant.id):
        record_consent(lien, granted_by=exploitant)
        assert consent_covers_current_scope(lien) is True

        FlwMappingFactory(tenant=tenant, link=lien, document_type="crm.CrmLead")

        assert consent_covers_current_scope(lien) is False, (
            "Une catégorie ajoutée après coup est couverte par un consentement "
            "qui ne la mentionne pas : le gel ne sert alors à rien."
        )
