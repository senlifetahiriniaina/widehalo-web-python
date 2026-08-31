"""Controle de facture a 3 voies (RG-PUR-6, §5.6.6, PU6 du sous-sequencement
`purchase` — cf. plan) : compare, pour chaque ligne d'une facture
fournisseur recue, la quantite COMMANDEE (`PurOrderLine.qty`/
`unit_price_mga`), la quantite RECUE (`PurOrderLine.qty_received`, deja
tracee depuis PU5) et la quantite/prix FACTURES — un ecart superieur au
seuil bloque la validation et ouvre un litige (acceptance test §5.6.7 n°4).

Premiere fois que `purchase` a besoin d'`accounting` (regle de couplage
n°1 respectee : uniquement `apps.accounting.services.public`, jamais
`apps.accounting.models` — cf. `apps/purchase/module.py`).

Discipline `attempt_transition` (garde-fou T7) : ce fichier n'appelle
JAMAIS `attempt_transition(...)` directement — il delegue exclusivement
aux fonctions deja conformes de `services/orders.py`
(`mark_order_invoiced`/`open_order_dispute`), qui rappellent elles-memes
`.save(update_fields=[...])` juste apres, cf. leur propre docstring."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from apps.accounting.services.public import create_supplier_invoice_from_source
from apps.core.models.user import User
from apps.purchase.models import PurCri, PurOrder, PurOrderLine
from apps.purchase.services.cri import create_cri
from apps.purchase.services.orders import mark_order_invoiced, open_order_dispute

# RG-PUR-6 : "seuil parametrable, defaut 2%" (§5.6.6 du CDC) — modifiable
# par appelant (`threshold_pct` de `three_way_match`/`record_supplier_
# invoice`), jamais code en dur ailleurs dans ce module.
DEFAULT_VARIANCE_THRESHOLD_PCT = Decimal("2")


def three_way_match(
    order: PurOrder,
    *,
    invoice_lines: list[dict[str, Any]],
    threshold_pct: Decimal = DEFAULT_VARIANCE_THRESHOLD_PCT,
) -> dict[str, Any]:
    """Compare, LIGNE PAR LIGNE, le montant COMMANDE (`order_line.qty *
    order_line.unit_price_mga`) au montant FACTURE (`qty_invoiced *
    unit_price_mga` fournis par l'appelant dans `invoice_lines`) — ne
    compare PAS le montant RECU separement : le CDC (§5.6.6) decrit un
    controle "commande/reception/facture" ou la reception sert de
    PREALABLE (une ligne non receptionnee ne devrait normalement pas etre
    facturable, garde deja assuree en amont par le cycle de vie de
    `PurOrder`/`receive_order_line`, PU5), pas un troisieme montant a
    comparer numeriquement en plus du montant commande — le montant
    RECU EN QUANTITE (`order_line.qty_received`) est neanmoins expose dans
    le detail retourne, pour tracabilite complete des 3 informations.

    `invoice_lines` : `[{"order_line_id": UUID, "qty_invoiced": Decimal,
    "unit_price_mga": Decimal}, ...]` — primitives uniquement, jamais un
    objet `PurOrderLine` passe par l'appelant (meme discipline que le
    reste de ce sous-sequencement).

    **Cas limite documente (division par zero)** : si `ordered_amount ==
    0` (ligne commandee gratuitement ou jamais chiffree) ET que
    `invoiced_amount != 0`, l'ecart est traite comme BLOQUANT a 100% —
    jamais une division par zero silencieusement ignoree, et jamais un
    ecart "infini" invraisemblable non plus : facturer un montant non nul
    sur une ligne commandee a 0 est TOUJOURS un ecart maximal par
    construction. Si `ordered_amount == 0` ET `invoiced_amount == 0`,
    l'ecart est 0% (rien facture sur rien commande, coherent).

    Retourne `{"lines": [...detail par ligne...], "blocked": bool,
    "max_variance_pct": Decimal}` — `blocked=True` des qu'UNE SEULE ligne
    depasse `threshold_pct`."""
    lines_by_id = {line.id: line for line in order.lines.all()}

    rows: list[dict[str, Any]] = []
    max_variance_pct = Decimal(0)
    blocked = False
    for entry in invoice_lines:
        order_line: PurOrderLine = lines_by_id[entry["order_line_id"]]
        qty_invoiced = Decimal(entry["qty_invoiced"])
        unit_price_invoiced = Decimal(entry["unit_price_mga"])

        ordered_amount = order_line.qty * order_line.unit_price_mga
        invoiced_amount = qty_invoiced * unit_price_invoiced

        if ordered_amount == 0:
            variance_pct = Decimal(100) if invoiced_amount != 0 else Decimal(0)
        else:
            variance_pct = (abs(invoiced_amount - ordered_amount) / ordered_amount) * Decimal(100)

        line_blocked = variance_pct > threshold_pct
        blocked = blocked or line_blocked
        max_variance_pct = max(max_variance_pct, variance_pct)

        rows.append(
            {
                "order_line_id": order_line.id,
                "description": order_line.description,
                "qty_ordered": order_line.qty,
                "qty_received": order_line.qty_received,
                "unit_price_ordered_mga": order_line.unit_price_mga,
                "ordered_amount_mga": ordered_amount,
                "qty_invoiced": qty_invoiced,
                "unit_price_invoiced_mga": unit_price_invoiced,
                "invoiced_amount_mga": invoiced_amount,
                "variance_pct": variance_pct,
                "blocked": line_blocked,
            }
        )

    return {"lines": rows, "blocked": blocked, "max_variance_pct": max_variance_pct}


def _dispute_reason(match: dict[str, Any], *, threshold_pct: Decimal) -> str:
    blocked_lines = [row for row in match["lines"] if row["blocked"]]
    details = ", ".join(
        f"{row['description']} ({row['variance_pct']:.2f}%)" for row in blocked_lines
    )
    return _(
        "Controle facture 3 voies (RG-PUR-6) : écart supérieur au seuil "
        "(%(threshold)s%%) sur %(count)s ligne(s) : %(details)s"
    ) % {"threshold": threshold_pct, "count": len(blocked_lines), "details": details}


def record_supplier_invoice(
    order: PurOrder,
    *,
    invoice_lines: list[dict[str, Any]],
    date: dt.date,
    user: User,
    threshold_pct: Decimal = DEFAULT_VARIANCE_THRESHOLD_PCT,
) -> dict[str, Any]:
    """Point d'entree RG-PUR-6 : `three_way_match` d'abord, puis SOIT bloque
    (litige, aucune facture creee) SOIT materialise la facture comptable
    et fait avancer la commande.

    **Chemin bloque** (acceptance test §5.6.7 n°4 : "Une facture superieure
    de 5% au bon de commande bloque la validation et ouvre un litige") :
    AUCUNE `AccMove` n'est creee — `open_order_dispute` (PU4, deja
    conforme `attempt_transition`) est appele avec un motif recapitulant
    les lignes en ecart. **PU7 (RG-PUR-8, cf. plan)** : un `PurCri` de type
    `litige` est desormais AUSSI cree en plus (effet de bord minimal et
    documente, ne change rien au contrat de retour existant ci-dessous —
    tous les tests PU6 restent inchanges) : `open_order_dispute` ne fait
    qu'ouvrir un ETAT sur la commande (un seul champ texte), `PurCri` est
    l'entite riche demandee par le CDC pour le suivi d'incident (cout/
    impact/action corrective), cf. docstring `models.py::PurCri`. Retourne
    `{"invoice_id": None, "match": ..., "dispute_opened": True}`.

    **Chemin conforme** : `accounting.services.public.
    create_supplier_invoice_from_source` est appele (primitives uniquement
    — jamais un objet `AccAccount`/`PurOrderLine`, regle de couplage n°1).
    Si la configuration comptable du tenant est incomplete (gap de
    configuration, cf. docstring de ce gap), il retourne `None` : dans ce
    cas, ni `qty_invoiced` ni l'etat FSM de la commande ne sont modifies —
    une facture qui n'existe pas nulle part en comptabilite ne doit JAMAIS
    faire croire que la commande est facturee. Sinon, `PurOrderLine.
    qty_invoiced` est incremente ligne par ligne et la commande transite
    vers `invoiced` via `mark_order_invoiced` (PU4, deja conforme
    `attempt_transition` — c'est le point de cablage annonce par sa
    docstring)."""
    match = three_way_match(order, invoice_lines=invoice_lines, threshold_pct=threshold_pct)

    if match["blocked"]:
        dispute_reason = _dispute_reason(match, threshold_pct=threshold_pct)
        open_order_dispute(order, user, reason=dispute_reason)
        # `cost_mga` reste a 0 (defaut) : l'ecart mesure est un POURCENTAGE
        # (`max_variance_pct`), jamais un montant MGA directement
        # utilisable comme cout d'incident sans fabriquer une precision que
        # les donnees ne supportent pas (meme discipline "jamais de faux
        # chiffre" que le reste de ce sous-sequencement) — a chiffrer
        # manuellement par l'evaluateur via `close_cri` le cas echeant.
        create_cri(
            tenant=order.tenant,
            date=date,
            type=PurCri.TYPE_LITIGE,
            partner_id=order.partner_id,
            order=order,
            description=dispute_reason,
        )
        return {"invoice_id": None, "match": match, "dispute_opened": True}

    expense_lines = [
        {"account_id": None, "amount": row["invoiced_amount_mga"], "label": row["description"]}
        for row in match["lines"]
    ]
    invoice_id = create_supplier_invoice_from_source(
        tenant=order.tenant,
        partner_id=order.partner_id,
        date=date,
        expense_lines=expense_lines,
        currency=order.currency,
    )
    if invoice_id is None:
        return {"invoice_id": None, "match": match, "dispute_opened": False}

    lines_by_id = {line.id: line for line in order.lines.all()}
    for entry in invoice_lines:
        order_line = lines_by_id[entry["order_line_id"]]
        order_line.qty_invoiced = order_line.qty_invoiced + Decimal(entry["qty_invoiced"])
        order_line.save(update_fields=["qty_invoiced"])

    mark_order_invoiced(order, user)

    return {"invoice_id": invoice_id, "match": match, "dispute_opened": False}
