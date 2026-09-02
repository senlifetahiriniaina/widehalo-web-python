"""Contrat public de l'app `financing` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Vide au demarrage du module (FIN1), comme `sales.services.public`/
`purchase.services.public`/`logistics.services.public` l'etaient a leur
premiere etape.

2 gaps ajoutes par PT9 du chantier "fiche partenaire a onglets par role"
(cf. plan) : `list_loan_applications_for_bank_partner` et
`list_credocs_for_bank_partner`.

`FinLoanApplication.bank_partner_id` confirme exact (verifie en lisant
`apps/financing/models.py` avant d'ecrire ce gap, comme demande par le
plan). **Deviation a signaler** : `FinCredoc` n'a PAS de
`bank_partner_id` propre — seulement un `bank` en texte libre
(`CharField`, saisie manuelle, jamais un UUID) et une FK optionnelle
`loan_application` vers `FinLoanApplication` (nullable : un CREDOC peut
naitre directement sans dossier de pret associe). `list_credocs_for_
bank_partner` ne peut donc retrouver que les CREDOC dont
`loan_application` est renseigne ET dont ce dossier porte le
`bank_partner_id` demande — un CREDOC cree directement (sans dossier)
n'apparaitra JAMAIS dans cette liste, quel que soit son champ `bank`
texte libre, faute d'UUID exploitable pour le relier a un `Partner`."""

from __future__ import annotations

from typing import Any

from apps.financing.models import FinCredoc, FinLoanApplication


def list_loan_applications_for_bank_partner(
    partner_id: Any, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Alimente l'onglet "Banque" de la fiche partenaire avec les
    `FinLoanApplication` rattachees a ce partenaire bancaire —
    `partners` ne doit jamais importer `apps.financing.models` (regle
    de couplage n°1).

    Retourne des dicts primitifs `{"id", "reference", "type",
    "amount_requested_mga", "state"}`, jamais l'objet
    `FinLoanApplication`, tries par `created_at` decroissant (dossier le
    plus recent en premier — `FinLoanApplication` n'a pas de champ
    `date` unique). Liste vide, jamais d'exception, si aucun dossier ne
    correspond a ce `partner_id`."""
    applications = FinLoanApplication.objects.filter(bank_partner_id=partner_id).order_by(
        "-created_at"
    )[:limit]
    return [
        {
            "id": application.id,
            "reference": application.reference,
            "type": application.type,
            "amount_requested_mga": application.amount_requested_mga,
            "state": application.state,
        }
        for application in applications
    ]


def list_credocs_for_bank_partner(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Alimente l'onglet "Banque" de la fiche partenaire avec les
    `FinCredoc` dont le `loan_application` rattache porte ce
    `bank_partner_id` — cf. docstring du module ci-dessus pour la
    deviation signalee (les CREDOC crees sans dossier de pret associe
    n'ont aucun UUID exploitable et ne peuvent jamais apparaitre ici).

    Retourne des dicts primitifs `{"id", "reference", "bank", "amount_
    mga", "state"}`, jamais l'objet `FinCredoc`, tries par `created_at`
    decroissant. Liste vide, jamais d'exception, si aucun CREDOC ne
    correspond a ce `partner_id`."""
    credocs = FinCredoc.objects.filter(loan_application__bank_partner_id=partner_id).order_by(
        "-created_at"
    )[:limit]
    return [
        {
            "id": credoc.id,
            "reference": credoc.reference,
            "bank": credoc.bank,
            "amount_mga": credoc.amount_mga,
            "state": credoc.state,
        }
        for credoc in credocs
    ]
