"""INT2 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `catalog` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_supplier_
info_missing_price` ne fait QUE surfacer `ProductSupplierInfo.price_mga`,
DEJA porte par le modele (defaut `0`, jamais recalcule ici) — une fiche
fournisseur sans prix renseigne est une incoherence de referentiel
directement exploitable (ex. par `purchase.services.orders` qui s'appuie
sur ce prix pour la selection multi-fournisseurs, RG-PUR-1)."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)


def _check_supplier_info_missing_price(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.catalog.models import ProductSupplierInfo

    infos = ProductSupplierInfo.objects.filter(
        tenant_id=tenant_id, is_active=True, price_mga__lte=0
    ).select_related("variant")

    return [
        AnomalyCandidate(
            content_type_label="catalog.productsupplierinfo",
            object_id=str(info.id),
            severity=SEVERITY_MEDIUM,
            description=(
                f"Information fournisseur de la variante « {info.variant.reference} » "
                f"(fournisseur {info.partner_id}) sans prix renseigne."
            ),
        )
        for info in infos
    ]


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "catalog.supplier_info_missing_price",
        module="catalog",
        label="Information fournisseur sans prix renseigne",
        function=_check_supplier_info_missing_price,
    )
