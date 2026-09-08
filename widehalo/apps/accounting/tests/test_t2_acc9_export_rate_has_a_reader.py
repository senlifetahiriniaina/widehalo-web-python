"""T2 (ACC-9) — `tva.taux_export` cesse d'être décoratif, sans qu'aucune
règle fiscale ne soit inventée.

**Ce qui a été trouvé.** La migration `accounting/0032` sème deux
paramètres réglementaires. Le premier, `tva.seuil_assujettissement`, est lu
par un calcul actif — et échappait au verrou OECFM. Le second,
`tva.taux_export`, n'était lu par **personne** : semé, versionné, référencé
dans une table d'amorçage du cahier, et invisible du produit. C'est
exactement le défaut que ce dépôt traque depuis le début, et il était cette
fois dans un paramètre de loi.

**Ce qui a été écarté, et il faut le dire.** L'issue apparente était de le
brancher sur le calcul de TVA de `sales`, en l'appliquant aux lignes des
commandes marquées `is_export` — le champ existe. Elle a été écartée : le
régime des exportations n'est pas « un taux différent », c'est une
exonération avec ses propres conditions de preuve, sa propre ligne de
déclaration et son propre traitement de la TVA d'amont. Un taux à 0 %
appliqué mécaniquement produirait des factures qui ont l'air justes et une
déclaration qui ne l'est pas. La réserve portée par le paramètre lui-même
— « À CONFIRMER OECFM/DGI (source non primaire) » — dit précisément qu'on
ne sait pas encore ce qu'il faut faire.

**Ce qui a été retenu** : l'écran de configuration fiscale l'affiche, avec
sa référence légale et son statut de validation. Le comptable qui paramètre
le régime a besoin de savoir ce que le produit connaît du taux d'export et
de voir qu'il n'est pas validé. Le paramètre a un lecteur de production ;
aucune règle n'a été fabriquée.
"""

from __future__ import annotations

import pytest

from apps.accounting.services.vat_reference import (
    VAT_EXPORT_RATE_CODE,
    resolve_export_vat_rate,
)
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.regulatory_governance import ACTIVE_CALCULATION_PARAMETER_CODES
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _tenant(code: str) -> Tenant:
    return Tenant.objects.create(code=code, name=f"Société {code}")


def _logged_in_client(tenant: Tenant, email: str):
    """L'utilisateur naît DANS le contexte de sa société.

    `User` hérite de `BaseModel`, donc de la RLS : créé hors contexte, il
    n'appartient à aucune société et l'écran redirige. Même montage que
    `test_l17_synthetic_regime.py`, dont cet écran vient."""
    from django.test import Client

    with use_tenant(tenant.id):
        User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(User.objects.get(email=email))
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_the_export_rate_is_resolvable_and_carries_its_reserve() -> None:
    """Le paramètre existe, il se lit, et il se lit AVEC son statut.

    Sans le statut, l'écran afficherait un taux comme s'il faisait foi."""
    tenant = _tenant("ACC9-EXPORT")
    with use_tenant(tenant.id):
        taux = resolve_export_vat_rate(tenant)
    assert taux is not None, (
        "`tva.taux_export` n'est plus résolvable : la migration d'amorçage a-t-elle été retirée ?"
    )
    assert taux["est_valide"] is False, (
        "Le taux d'export est marqué validé OECFM. Le cahier interdit de "
        "lever une réserve réglementaire par défaut (§0.5)."
    )
    assert "OECFM" in taux["reference_legale"] or "CONFIRMER" in taux["reference_legale"]


def test_the_fiscal_screen_shows_the_export_rate_and_says_it_is_not_applied() -> None:
    """LE lecteur de production. Sans lui, le paramètre reste décoratif —
    et ce test est ce qui l'empêche de le redevenir."""
    tenant = _tenant("ACC9-ECRAN")
    client = _logged_in_client(tenant, "acc9-ecran@example.com")

    corps = client.get("/accounting/config/fiscal/").content.decode()
    assert "exportation" in corps.lower(), (
        "L'écran de configuration fiscale n'affiche plus le taux d'export : "
        "`tva.taux_export` redevient un paramètre que personne ne lit."
    )
    assert "appliqué à aucun calcul" in corps, (
        "L'écran affiche le taux sans dire qu'il n'est pas appliqué — c'est "
        "présenter une valeur non validée comme une règle en vigueur."
    )


def test_the_export_rate_is_deliberately_outside_the_deployment_gate() -> None:
    """Conséquence assumée, et écrite pour ne pas être « corrigée » plus
    tard par distraction.

    Le critère ACC-9 gouverne les paramètres « utilisés par un calcul
    actif ». Celui-ci est lu par un AFFICHAGE. L'y mettre bloquerait un
    déploiement au nom d'une valeur qu'aucun calcul ne consomme, et
    diluerait le sens du verrou — qui vaut par ce qu'il refuse. Le jour où
    le régime d'export sera réellement implémenté, ce code y entrera avec
    lui, et ce test sera à retourner."""
    assert VAT_EXPORT_RATE_CODE not in ACTIVE_CALCULATION_PARAMETER_CODES


def test_a_malformed_export_rate_shows_nothing_rather_than_a_wrong_number() -> None:
    """Un paramètre saisi à la main peut porter n'importe quoi. Mieux vaut
    ne rien afficher qu'un taux inventé — même posture que
    `resolve_vat_liability_thresholds`."""
    tenant = _tenant("ACC9-CASSE")
    RegulatoryParameter.objects.filter(code=VAT_EXPORT_RATE_CODE, tenant__isnull=True).update(
        value="pas un nombre"
    )
    with use_tenant(tenant.id):
        assert resolve_export_vat_rate(tenant) is None
