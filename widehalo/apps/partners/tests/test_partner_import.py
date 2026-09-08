"""Import du referentiel partenaires depuis un fichier xlsx — jeu de
donnees synthetique (jamais un fichier reel), cf. docs/IMPORT_FORMATS.md."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.partner_import import (
    PARTNER_FORMAT_VERSION,
    import_partners_xlsx,
)

pytestmark = pytest.mark.django_db


def _build_xlsx(rows: list[list[object]], *, header: list[str] | None = None) -> bytes:
    header = header or [
        "Code",
        "Nom",
        "NIF",
        "Roles",
        "Credit_limit_mga",
        "Email",
        "Phone",
        "Address",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_creates_partners_with_role_translation() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client SARL", "NIF001", "client", 500000, "", "", ""],
            ["P002", "Fournisseur Textile", "NIF002", "fournisseur;transporteur", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes, filename="partenaires.xlsx")

        assert summary.is_valid
        assert summary.created_count == 2
        assert summary.skipped_existing_count == 0

        client_partner = Partner.objects.get(tenant=tenant, reference="P001")
        assert client_partner.roles == [Partner.ROLE_CLIENT]
        supplier_partner = Partner.objects.get(tenant=tenant, reference="P002")
        assert supplier_partner.roles == [Partner.ROLE_SUPPLIER, Partner.ROLE_CARRIER]


def test_import_is_idempotent_by_code() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["P001", "Client SARL", "", "client", 0, "", "", ""]])

    with use_tenant(tenant.id):
        import_partners_xlsx(tenant, file_bytes)
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.created_count == 0
        assert summary.skipped_existing_count == 1
        assert Partner.objects.filter(tenant=tenant, reference="P001").count() == 1


def test_import_flags_duplicate_nif_without_blocking() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client A", "SAMENIF", "client", 0, "", "", ""],
            ["P002", "Client B (doublon NIF)", "SAMENIF", "client", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 2
        assert summary.duplicate_alerts_count == 1
        assert DuplicateAlert.objects.filter(tenant=tenant).count() == 1


def test_import_matches_two_spellings_of_the_same_nif() -> None:
    """T3 — le rapprochement porte sur la forme CANONIQUE.

    Avant ce lot, l'import comparait les chaines brutes : deux feuilles du
    meme client, l'une avec tirets et l'autre sans, produisaient deux fiches
    sans la moindre alerte — c'est-a-dire que la detection ne servait que
    dans le cas ou l'utilisateur avait deja fait attention.

    Les deux ecritures sont conservees telles quelles : normaliser d'office
    reecrirait la saisie du comptable, et l'une des deux formes peut etre
    la forme officielle."""
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client A", "MG-NIF-100002", "client", 0, "", "", ""],
            ["P002", "Client B", "mg nif 100002", "client", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 2
        assert summary.duplicate_alerts_count == 1
        assert Partner.objects.get(tenant=tenant, reference="P001").nif == "MG-NIF-100002"
        assert Partner.objects.get(tenant=tenant, reference="P002").nif == "MG NIF 100002"


#: Lectures de `partners_partner` qu'une ligne creee coute LEGITIMEMENT :
#: la verification d'existence de `save()` et la relecture des champs
#: audites pour le diff (`_AUDITED_FIELDS`). Les deux existaient avant T3.
#: Une TROISIEME serait le balayage de rapprochement des doublons, et c'est
#: exactement ce que ce budget refuse.
LECTURES_LEGITIMES_PAR_LIGNE = 2


def test_import_does_not_rescan_the_whole_referential_for_every_row() -> None:
    """Le rapprochement canonique ne doit pas coûter une lecture PAR LIGNE.

    Le rapprochement se fait en Python — comparer en SQL supposerait de
    reproduire `canonical`, qui divergerait sur les valeurs anterieures a
    T3 (aucune migration ne les a normalisees, deliberement). Le refaire
    par une requete a chaque ligne creee rendrait l'import quadratique en
    lignes examinees, sur un chemin qui ne faisait aucune requete de ce
    genre avant T3.

    **Comment ce test mesure, et pourquoi pas autrement.** Une premiere
    redaction comptait les lectures « sans filtre sur la clef primaire » :
    elle ne mordait pas, parce que le balayage fautif s'ecrit
    `.exclude(pk=...)` et porte donc bien la clef primaire — dans un `NOT`.
    Une seconde comptait toutes les lectures et exigeait un total : elle
    echouait sur les deux lectures que `save()` fait par ligne depuis
    toujours.

    Ce qui discrimine reellement, c'est le COUT MARGINAL : on importe deux
    fichiers de tailles differentes et on divise l'ecart de requetes par
    l'ecart de lignes. Deux lectures par ligne sont legitimes ; une
    troisieme est le balayage."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def _lectures(nombre_de_lignes: int) -> int:
        tenant = TenantFactory()
        lignes = [
            [
                f"P{index:03d}",
                f"Client {index}",
                f"MG-NIF-3{index:04d}",
                "client",
                0,
                "",
                "",
                "",
            ]
            for index in range(nombre_de_lignes)
        ]
        file_bytes = _build_xlsx(lignes)
        with use_tenant(tenant.id), CaptureQueriesContext(connection) as requetes:
            summary = import_partners_xlsx(tenant, file_bytes)
        assert summary.created_count == nombre_de_lignes
        return len(
            [
                requete
                for requete in requetes.captured_queries
                if 'FROM "partners_partner"' in requete["sql"]
            ]
        )

    petit, grand = 5, 25
    cout_marginal = (_lectures(grand) - _lectures(petit)) / (grand - petit)
    assert cout_marginal <= LECTURES_LEGITIMES_PAR_LIGNE, (
        f"{cout_marginal} lecture(s) de partners_partner par ligne creee, "
        f"pour un budget de {LECTURES_LEGITIMES_PAR_LIGNE} : le rapprochement "
        "des doublons refait un balayage a chaque ligne."
    )


def test_import_reports_row_errors_without_writing_anything() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client valide", "", "client", 0, "", "", ""],
            # Role inconnu -> ArrayField choices invalide -> row error.
            ["P002", "Client invalide", "", "role_invalide", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert not summary.is_valid
        assert len(summary.row_errors) == 1
        assert summary.row_errors[0].row_index == 1
        assert not Partner.objects.filter(tenant=tenant).exists()


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["P001", "Client", "", "client", 0, "", "", ""]])

    with use_tenant(tenant.id):
        with pytest.raises(ValueError, match="non supporté"):
            import_partners_xlsx(tenant, file_bytes, format_version=PARTNER_FORMAT_VERSION + 1)
        assert not Partner.objects.filter(tenant=tenant).exists()


def test_import_accepts_canonical_header_aliases_and_ignores_coordinates() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [["P010", "Client", "", "client", 0, "client@example.com", "0340000000", "Antananarivo"]],
        header=["CODE", "NAME", "NIF", "ROLES", "CREDIT_LIMIT_MGA", "EMAIL", "PHONE", "ADDRESS"],
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 1
        assert summary.coordinates_ignored_count == 1
