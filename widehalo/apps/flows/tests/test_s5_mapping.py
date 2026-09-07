"""S5 — FLX-6 : une correspondance incomplète est refusée À
L'ENREGISTREMENT, en nommant le champ.

Le critère a deux moitiés, et c'est la seconde qui décide de l'architecture :
« Refuse à l'enregistrement toute correspondance incomplète sur un champ
obligatoire du tiers, **plutôt que d'échouer au premier envoi** ». Une
correspondance incomplète acceptée en base n'explose qu'au premier échange
réel, chez le tiers, sur la pièce d'un client — au moment où plus personne
ne se souvient de l'avoir configurée.

Ces tests exercent donc `save_mapping`, jamais seulement `validate_mapping` :
ce qui compte est que la BASE ne contienne pas la correspondance fautive.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwMapping
from apps.flows.services.mapping import (
    PROBLEM_INVALID_PARAMETER,
    PROBLEM_MISSING_PARAMETER,
    PROBLEM_TOO_MANY_SOURCES,
    PROBLEM_UNKNOWN_TARGET_FIELD,
    PROBLEM_UNKNOWN_TRANSFORM,
    TransformationError,
    apply_mapping,
    save_mapping,
    validate_mapping,
)
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db


#: Le schéma que le tiers DÉCLARE. Trois champs obligatoires, un
#: facultatif — la forme la plus banale d'un formulaire fiscal.
SCHEMA_TIERS = {
    "fields": {
        "nif": {"required": True, "type": "string"},
        "date_piece": {"required": True, "type": "date"},
        "montant": {"required": True, "type": "decimal"},
        "commentaire": {"required": False, "type": "string"},
    }
}

CORRESPONDANCE_COMPLETE = {
    "nif": {"source": "partenaire.nif"},
    "date_piece": {
        "source": "date",
        "transform": "format_date",
        "params": {"format": "%d/%m/%Y"},
    },
    "montant": {
        "source": "total",
        "transform": "separateur_decimal",
        "params": {"separateur": ","},
    },
}


@pytest.fixture
def liaison():
    """La liaison naît DANS le contexte de sa société : hors contexte, la
    Row-Level Security refuse l'insertion (`new row violates row-level
    security policy`), et le message ne désigne pas la cause."""
    societe = Tenant.objects.create(code="S5-MAP", name="Correspondances SARL")
    with use_tenant(societe.id):
        return FlwLinkFactory(tenant=societe)


def test_a_complete_mapping_is_saved(liaison) -> None:
    with use_tenant(liaison.tenant_id):
        mapping = save_mapping(
            liaison.tenant,
            liaison,
            document_type="facture_vente",
            field_map=CORRESPONDANCE_COMPLETE,
            target_schema=SCHEMA_TIERS,
        )
    assert mapping.pk is not None
    assert mapping.field_map == CORRESPONDANCE_COMPLETE


def test_a_missing_required_field_is_refused_and_named(liaison) -> None:
    """LE critère. Le refus doit NOMMER le champ : un message « correspondance
    incomplète » obligerait l'utilisateur à comparer deux JSON à l'œil."""
    incomplete = dict(CORRESPONDANCE_COMPLETE)
    del incomplete["montant"]

    with use_tenant(liaison.tenant_id), pytest.raises(ValidationError) as refus:
        save_mapping(
            liaison.tenant,
            liaison,
            document_type="facture_vente",
            field_map=incomplete,
            target_schema=SCHEMA_TIERS,
        )

    assert "montant" in str(refus.value), (
        f"Le refus ne désigne pas le champ manquant : {refus.value}"
    )
    with use_tenant(liaison.tenant_id):
        assert not FlwMapping.objects.filter(link=liaison).exists(), (
            "La correspondance fautive a été écrite : le refus est arrivé APRÈS "
            "l'enregistrement, ce que FLX-6 interdit explicitement."
        )


def test_all_the_missing_fields_are_named_at_once(liaison) -> None:
    """Un éditeur qui ne signale qu'un défaut à la fois fait recommencer
    l'utilisateur autant de fois qu'il y a de champs."""
    rapport = validate_mapping({"nif": {"source": "x"}}, SCHEMA_TIERS)
    assert sorted(rapport.missing_required_fields) == ["date_piece", "montant"]


def test_an_optional_field_may_be_left_unmapped(liaison) -> None:
    """La contrepartie — sans elle, la garde exigerait de renseigner des
    champs que le tiers dit facultatifs, et on remplirait des colonnes pour
    faire taire un test."""
    rapport = validate_mapping(CORRESPONDANCE_COMPLETE, SCHEMA_TIERS)
    assert rapport.is_valid
    assert "commentaire" not in CORRESPONDANCE_COMPLETE


def test_a_field_the_third_party_never_declared_is_refused(liaison) -> None:
    """Minimisation, et ce n'est pas du pédantisme : « La correspondance de
    champs ne peut pas ajouter un champ non déclaré nécessaire » (cahier,
    protection des données). Un champ en trop PART quand même chez le
    tiers — c'est une donnée personnelle qui sort sans motif."""
    avec_extra = {**CORRESPONDANCE_COMPLETE, "marge_commerciale": {"source": "marge"}}
    rapport = validate_mapping(avec_extra, SCHEMA_TIERS)
    assert not rapport.is_valid
    assert [p.kind for p in rapport.problems] == [PROBLEM_UNKNOWN_TARGET_FIELD]
    assert rapport.problems[0].target_field == "marge_commerciale"


def test_a_transformation_outside_the_closed_set_is_refused(liaison) -> None:
    hors_jeu = {
        **CORRESPONDANCE_COMPLETE,
        "commentaire": {"source": "note", "transform": "expression_libre"},
    }
    rapport = validate_mapping(hors_jeu, SCHEMA_TIERS)
    assert [p.kind for p in rapport.problems] == [PROBLEM_UNKNOWN_TRANSFORM]


def test_a_transformation_without_its_parameter_is_refused_before_saving(liaison) -> None:
    """Le paramètre manquant est exactement le défaut qui « échoue au
    premier envoi » si on ne le cherche pas à l'enregistrement : la
    correspondance a l'air complète, tous les champs sont couverts, et
    `strftime(None)` explose devant le tiers."""
    sans_format = {
        **CORRESPONDANCE_COMPLETE,
        "date_piece": {"source": "date", "transform": "format_date"},
    }
    rapport = validate_mapping(sans_format, SCHEMA_TIERS)
    assert [p.kind for p in rapport.problems] == [PROBLEM_MISSING_PARAMETER]
    assert rapport.problems[0].target_field == "date_piece"


def test_an_unknown_case_is_refused(liaison) -> None:
    mauvaise_casse = {
        **CORRESPONDANCE_COMPLETE,
        "commentaire": {"source": "note", "transform": "casse", "params": {"casse": "PascalCase"}},
    }
    rapport = validate_mapping(mauvaise_casse, SCHEMA_TIERS)
    assert [p.kind for p in rapport.problems] == [PROBLEM_INVALID_PARAMETER]


def test_only_concatenation_accepts_several_sources(liaison) -> None:
    """L'arbitrage de l'axe A2 : la prose dit « un pour un », la liste des
    six inclut la concaténation. Le critère l'emporte, et la concaténation
    est la seule exception."""
    plusieurs_sources_sur_une_casse = {
        **CORRESPONDANCE_COMPLETE,
        "commentaire": {
            "sources": ["a", "b"],
            "transform": "casse",
            "params": {"casse": "majuscules"},
        },
    }
    rapport = validate_mapping(plusieurs_sources_sur_une_casse, SCHEMA_TIERS)
    assert [p.kind for p in rapport.problems] == [PROBLEM_TOO_MANY_SOURCES]

    concatenation = {
        **CORRESPONDANCE_COMPLETE,
        "commentaire": {
            "sources": ["a", "b"],
            "transform": "concatenation",
            "params": {"separateur": " "},
        },
    }
    assert validate_mapping(concatenation, SCHEMA_TIERS).is_valid


def test_an_empty_third_party_schema_validates_nothing(liaison) -> None:
    """Une correspondance validée contre un schéma vide serait validée
    contre RIEN, et rendrait « valide » — le pire des deux mondes, puisque
    l'utilisateur croirait avoir été contrôlé."""
    rapport = validate_mapping(CORRESPONDANCE_COMPLETE, {})
    assert not rapport.is_valid


def test_saving_twice_updates_instead_of_duplicating(liaison) -> None:
    """La contrainte d'unicité (tenant, liaison, type de pièce) rendrait un
    second enregistrement fatal ; un éditeur doit pouvoir corriger."""
    with use_tenant(liaison.tenant_id):
        save_mapping(
            liaison.tenant,
            liaison,
            document_type="facture_vente",
            field_map=CORRESPONDANCE_COMPLETE,
            target_schema=SCHEMA_TIERS,
        )
        corrigee = {**CORRESPONDANCE_COMPLETE, "commentaire": {"source": "note"}}
        save_mapping(
            liaison.tenant,
            liaison,
            document_type="facture_vente",
            field_map=corrigee,
            target_schema=SCHEMA_TIERS,
        )
        assert FlwMapping.objects.filter(link=liaison).count() == 1
        assert FlwMapping.objects.get(link=liaison).field_map == corrigee


# --- Les six transformations, appliquées ------------------------------------
#
# Une transformation déclarée et jamais appliquée serait une énumération
# décorative — le motif que ce dépôt corrige depuis le début. Chacune est
# donc exercée sur une valeur réelle.


def test_the_six_transformations_produce_what_the_third_party_expects() -> None:
    document = {
        "partenaire": {"nif": "1234567890"},
        "date": dt.date(2026, 6, 26),
        "total": Decimal("1500.75"),
        "prenom": "Rakoto",
        "nom": "Andrianina",
        "regime": "RS",
        "note": "facture de test",
    }
    field_map = {
        "nif": {"source": "partenaire.nif"},
        "date_piece": {
            "source": "date",
            "transform": "format_date",
            "params": {"format": "%d/%m/%Y"},
        },
        "montant": {
            "source": "total",
            "transform": "separateur_decimal",
            "params": {"separateur": ","},
        },
        "libelle": {"source": "note", "transform": "casse", "params": {"casse": "majuscules"}},
        "nom_complet": {
            "sources": ["prenom", "nom"],
            "transform": "concatenation",
            "params": {"separateur": " "},
        },
        "emetteur": {"transform": "valeur_constante", "params": {"valeur": "WIDEHALO"}},
        "code_regime": {
            "source": "regime",
            "transform": "table_de_correspondance",
            "params": {"table": {"RS": "01", "RE": "02"}},
        },
    }

    assert apply_mapping(field_map, document) == {
        "nif": "1234567890",
        "date_piece": "26/06/2026",
        "montant": "1500,75",
        "libelle": "FACTURE DE TEST",
        "nom_complet": "Rakoto Andrianina",
        "emetteur": "WIDEHALO",
        "code_regime": "01",
    }


def test_an_absent_optional_source_is_not_emitted_empty() -> None:
    """Envoyer une chaîne vide au tiers, c'est AFFIRMER que la valeur est
    vide ; ne rien envoyer, c'est dire qu'on ne la renseigne pas. Sur un
    formulaire fiscal, les deux ne se valent pas."""
    assert apply_mapping({"commentaire": {"source": "note"}}, {}) == {}


def test_an_unmapped_value_fails_where_it_can_be_seen() -> None:
    """Une valeur absente de la table de correspondance est une erreur de
    DONNÉE, pas de configuration : elle ne se découvre qu'avec une pièce
    réelle, et appartient à la famille `donnee_invalide` de S3."""
    field_map = {
        "code_regime": {
            "source": "regime",
            "transform": "table_de_correspondance",
            "params": {"table": {"RS": "01"}},
        }
    }
    with pytest.raises(TransformationError):
        apply_mapping(field_map, {"regime": "INCONNU"})

    avec_defaut = {
        "code_regime": {
            "source": "regime",
            "transform": "table_de_correspondance",
            "params": {"table": {"RS": "01"}, "defaut": "99"},
        }
    }
    assert apply_mapping(avec_defaut, {"regime": "INCONNU"}) == {"code_regime": "99"}
