"""Generation de codes-barres EAN-13/GTIN par variante -- T1 du cahier des
charges refonte UX ("codes-barres EAN/GTIN generes par variante", Sprint 4
/ L3, cf. docs/planning/2026-refonte-ux-sprints.md §5).

Lacune reelle comblee ici (cf. docs/planning/2026-refonte-ux-sprints.md
rapport d'exploration prealable) : `apps.stocks.services.barcodes.
generate_barcode_value` produit des identifiants internes libres
("PREFIX-IDENTIFIER"), explicitement documentes comme non conformes
EAN/GS1 et hors perimetre catalogue (couplage stocks/catalog interdit).
Ce module est le premier a implementer un VRAI EAN-13 (checksum GS1)
dans le depot.

Prefixe GS1 "20" (plage 200-299) : "restricted circulation numbers
within a company" -- reserve par GS1 pour un usage interne, valide SANS
adhesion GS1/prefixe d'entreprise attribue. Ne fabrique jamais un GTIN
pretendant a une portee internationale (ce serait usurper un prefixe
d'entreprise reel) ; a remplacer par un vrai prefixe GS1 si WideHalo
adhere un jour a GS1 pour une distribution grand public hors Madagascar."""

from __future__ import annotations

from django.db import transaction

from apps.catalog.models import ProductVariant
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant

EAN13_RESTRICTED_CIRCULATION_PREFIX = "20"
_EAN13_SEQUENCE_CODE = "EAN13"


def _ean13_check_digit(digits12: str) -> int:
    """Algorithme de cle de controle EAN-13 standard (GS1) : poids 1 sur
    les positions impaires (1-indexees), poids 3 sur les positions
    paires, sur les 12 premiers chiffres."""
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits12))
    return (10 - total % 10) % 10


def next_ean13(tenant: Tenant) -> str:
    """Prochain EAN-13 sequence pour ce tenant, verrouille en transaction
    (meme patron que `apps.core.services.sequences.next_reference`, mais
    un identifiant EAN doit rester un entier pur -- pas de prefixe/annee
    dans le corps du code, contrairement a une reference documentaire)."""
    with transaction.atomic():
        sequence, _created = Sequence.objects.select_for_update().get_or_create(
            tenant=tenant, code=_EAN13_SEQUENCE_CODE, fiscal_year=0
        )
        sequence.last_number += 1
        sequence.save(update_fields=["last_number"])
        number = sequence.last_number

    body = f"{EAN13_RESTRICTED_CIRCULATION_PREFIX}{number:010d}"
    return body + str(_ean13_check_digit(body))


def assign_ean13(variant: ProductVariant) -> ProductVariant:
    """Assigne un EAN-13 a `variant` s'il n'en a pas deja un (idempotent —
    rappeler sur une variante deja codee ne la recode jamais)."""
    if variant.ean13:
        return variant
    variant.ean13 = next_ean13(variant.tenant)
    variant.save(update_fields=["ean13"])
    return variant
