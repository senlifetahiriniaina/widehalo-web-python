"""ACC-FONCIER (§1.9 du document annexe) : impots locaux fonciers geres au
niveau communal — IFT (Impot Foncier sur les Terrains, 1% de la valeur
marchande du terrain nu) et IFPB (Impot Foncier sur la Propriete Batie, 5 a
10% de la valeur locative de l'immeuble, 1/3 de cette valeur pour le
residentiel). Priorite BASSE (V2 au CDC) : pertinent seulement si le tenant
est proprietaire de ses locaux/ateliers/entrepots.

Pas de generation automatique depuis le grand livre : une valeur fonciere
(valeur marchande du terrain, valeur locative de l'immeuble) est une donnee
de propriete, pas une ecriture comptable deja saisie ailleurs dans le
systeme — simple enregistrement manuel, cf. `record_local_tax`.

Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : les taux (1% IFT, 5-10%
ou 1/3 pour l'IFPB residentiel) sont repris d'un document non primaire, a
confirmer aupres de la commune/DGI competente avant tout usage en
production reelle — `rate_pct` reste TOUJOURS un parametre explicite fourni
par l'appelant, jamais un defaut devine par cette fonction (l'IFPB en
particulier n'a pas de taux unique)."""

from __future__ import annotations

from decimal import Decimal

from apps.accounting.models import AccFiscalYear, AccLocalTax
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference


def record_local_tax(
    *,
    tenant: Tenant,
    tax_type: str,
    property_label: str,
    assessed_value_mga: Decimal,
    rate_pct: Decimal,
    fiscal_year: AccFiscalYear,
) -> AccLocalTax:
    """Enregistre une ligne d'impot local foncier (IFT/IFPB) — CRUD simple,
    le montant du est calcule ici (`assessed_value_mga * rate_pct / 100`)
    plutot que laisse a la charge de l'appelant, seule logique metier de
    cette fonction."""
    amount_due = (assessed_value_mga * rate_pct / Decimal(100)).quantize(Decimal("0.0001"))
    return AccLocalTax.objects.create(
        tenant=tenant,
        reference=next_reference(tenant, tax_type.upper(), fiscal_year.date_start.year),
        tax_type=tax_type,
        property_label=property_label,
        assessed_value_mga=assessed_value_mga,
        rate_pct=rate_pct,
        fiscal_year=fiscal_year,
        amount_due_mga=amount_due,
    )
