"""TVA de vente cote `sales` (L5) — resolution du taux applicable a une
ligne, et recalcul des totaux HT / TVA / TTC d'un document.

**Le defaut ferme.** `sales` portait `tax_id` sur ses deux modeles de
ligne depuis S1, et les deux `_recompute_totals` ecrivaient
`amount_tax = Decimal(0)` en dur. Le champ n'etait renseigne par AUCUNE
surface d'entree — ni l'API, ni les vues, ni les seeds : il ne pouvait que
se propager par copie d'un document a l'autre, en partant toujours de
`None`. En bout de chaine, `invoicing.invoice_order` transmettait a
`accounting` des `income_lines` HORS TAXE et rien d'autre : **aucune
facture emise depuis une commande de vente n'a jamais credite un compte de
TVA collectee**, et `invoice_pdf` affichait donc une TVA de 0 sur chacune
d'elles. Le module qui facture les clients etait le seul du produit a ne
pas savoir facturer la taxe.

Le taux, lui, n'a jamais manque : `AccTax` existe, datee et par tenant,
`accounting.services.public.get_default_sale_tax` sait la lire, et le POS
l'applique depuis sa premiere version. C'est le meme patron que les autres
ecarts de ce chantier — le code etait juste, rien ne l'appelait.

**Ce que ce module NE fait pas.** Il ne choisit pas un taux par article :
`get_default_sale_tax` n'expose qu'un taux de vente par defaut, et
inventer ici une matrice taux-par-produit fabriquerait une regle fiscale
que ni le cahier ni la table `AccTax` ne portent (meme simplification
assumee, et pour la meme raison, que le POS). Une ligne peut en revanche
recevoir un `tax_id` explicite de son appelant, et son taux est alors relu
sur cette taxe-la."""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Sum

from apps.accounting.services.public import (
    get_default_sale_tax,
    get_sale_tax,
    is_vat_liable,
)
from apps.core.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Meme quantum que `subtotal` (`SalesOrderLine.subtotal`, 4 decimales) et
# que le POS (`pos.services.orders._AMOUNT_QUANT`).
AMOUNT_QUANT = Decimal("0.0001")


def resolve_line_tax(
    tenant: Tenant, *, on_date: dt.date, tax_id: UUID | None = None
) -> tuple[UUID | None, Decimal]:
    """Taxe a figer sur une ligne : `(tax_id, tax_rate)`.

    `tax_id` fourni -> ce taux-la, relu sur cette taxe. Absent -> la taxe
    de vente par defaut du tenant a `on_date` — la DATE DU DOCUMENT, jamais
    « aujourd'hui » : une commande saisie avec retard doit porter le taux
    en vigueur a sa date, pas celui du jour de la saisie.

    Retourne `(None, Decimal(0))` quand aucune taxe ne s'applique. **Deux
    causes tres differentes se rejoignent ici, et une seule est normale** :

    - un tenant NON ASSUJETTI (RG-ACC-5) vend legitimement sans TVA — rien
      a signaler, et surtout rien a journaliser : ecrire une ligne de
      journal a chaque ligne de chaque devis d'un tenant synthetique
      noierait le signal utile sous du bruit permanent ;
    - un tenant ASSUJETTI qui n'a configure aucune `AccTax` valide a cette
      date vend a 0 % par accident. C'est un gap de configuration, il doit
      se voir, et c'est un `warning` — pas un `info`.

    L5 les confondait faute de pouvoir lire le regime fiscal depuis
    `sales`. `accounting.services.public.is_vat_liable` (L17) le permet
    sans violer la regle de couplage n1, et le repli redevient ce qu'il
    aurait toujours du etre : silencieux quand il est normal, bruyant quand
    il ne l'est pas."""
    if tax_id is not None:
        tax: dict[str, Any] | None = get_sale_tax(tenant, tax_id)
    else:
        tax = get_default_sale_tax(tenant, on_date=on_date)
    if tax is None:
        if is_vat_liable(tenant):
            logger.warning(
                "Tenant %s assujetti a la TVA, mais aucune taxe de vente applicable le %s "
                "(tax_id=%s) : la ligne part a 0 %%. Configurer une AccTax de vente valide "
                "a cette date.",
                tenant.pk,
                on_date,
                tax_id,
            )
        return None, Decimal(0)
    rate: Decimal = tax["rate"]
    resolved_id: UUID = tax["id"]
    return resolved_id, rate


def line_tax_amount(subtotal: Decimal, tax_rate: Decimal) -> Decimal:
    """TVA d'une ligne, arrondie AU NIVEAU DE LA LIGNE.

    Arrondir par ligne plutot que sur le total du document n'est pas
    indifferent : les deux resultats different d'un centime des que
    plusieurs lignes tombent sur un demi-quantum, et le montant que le
    client signe doit etre celui que la facture reprend. Le POS arrondit
    par ligne (`pos.services.orders.add_line`), la facture reprend le
    montant fige — c'est cette convention-la qui est tenue ici de bout en
    bout."""
    return (subtotal * tax_rate / Decimal(100)).quantize(AMOUNT_QUANT)


def document_tax_total(lines: Any) -> tuple[Decimal, Decimal]:
    """`(amount_untaxed, amount_tax)` d'un document, depuis ses lignes.

    Le HT vient d'un agregat SQL (inchange), la TVA d'une somme des
    montants par ligne — elle ne peut pas etre un agregat SQL sans
    reintroduire l'arrondi global que `line_tax_amount` refuse."""
    amount_untaxed: Decimal = lines.aggregate(total=Sum("subtotal"))["total"] or Decimal(0)
    amount_tax = sum(
        (line_tax_amount(line.subtotal, line.tax_rate) for line in lines.all()),
        Decimal(0),
    )
    return amount_untaxed, amount_tax
