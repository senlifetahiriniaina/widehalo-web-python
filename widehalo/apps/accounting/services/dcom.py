"""ACC-DCOM1 (§1.8 du document annexe) : generation automatique de la
declaration du droit de communication (DCOM) — une obligation declarative
de recoupement (PAS un impot, Art. 20.06.12 al. 3 et 20.06.15 al. 4 du CGI),
due par toute entite dont le CA > 100 M Ar. Le document annexe est explicite
sur l'exigence : le module `accounting` doit pouvoir "generer automatiquement
le DCOM depuis les ecritures comptables (montants agreges par partenaire,
par nature de transaction)".

Reserve OECFM/DGI (§0.3, §0.5, §3.5 du document annexe) : la classification
"par nature de transaction" reprend, dans ce document, une reference aux "9
canevas normalises de transactions par tiers (classification des rubriques :
achats immobilises, etc.)" sans les enumerer integralement — le document ne
les detaille pas au-dela de cet exemple. Cette implementation utilise donc un
classement de repli RAISONNABLE mais PROVISOIRE : la classe PCG 2005
(`AccAccount.account_class`, 1 a 7) du compte de contrepartie de chaque
ligne d'ecriture, groupee par tiers. Ce n'est PAS la classification officielle
des 9 canevas DGI — a confirmer/reconcilier avec un expert-comptable OECFM ou
la DGI avant tout depot reel sur entreprises.impots.mg/dconline."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.accounting.models import (
    AccDcomDeclaration,
    AccDcomLine,
    AccFiscalYear,
    AccMove,
    AccMoveLine,
)
from apps.core.services.sequences import next_reference

# Classement de repli PAR CLASSE PCG (cf. reserve OECFM/DGI en tete de
# module) — pas les 9 canevas DGI exacts.
_CLASSIFICATION_BY_PCG_CLASS: dict[int, str] = {
    1: "capitaux",
    2: "immobilisations",
    3: "stocks",
    4: "tiers",
    5: "tresorerie",
    6: "achats",
    7: "ventes",
}
_CLASSIFICATION_FALLBACK = "autres"


def _classification_for(account_class: int) -> str:
    return _CLASSIFICATION_BY_PCG_CLASS.get(account_class, _CLASSIFICATION_FALLBACK)


def generate_dcom_declaration(fiscal_year: AccFiscalYear) -> AccDcomDeclaration:
    """Agrege toutes les lignes d'ecriture PUBLIEES de l'exercice portant un
    `partner_id` non nul, groupees par (tiers, classe PCG du compte de
    contrepartie), et cree/rafraichit la declaration DCOM correspondante.

    Idempotent PAR EXERCICE (cf. §1.8 du document annexe, "generation
    automatique") : une seule `AccDcomDeclaration` par `fiscal_year` — si
    une declaration existe deja pour cet exercice, ses lignes sont
    supprimees et regenerees SUR LA MEME declaration (pas de nouvelle ligne
    d'historique par regeneration) ; c'est un choix assume plus simple que
    la conservation d'un historique de versions, coherent avec le fait que
    la DCOM est un etat RECALCULE depuis le grand livre a chaque
    generation, jamais une saisie manuelle a preserver."""
    declaration, created = AccDcomDeclaration.objects.get_or_create(
        tenant=fiscal_year.tenant, fiscal_year=fiscal_year
    )
    if created:
        declaration.reference = next_reference(
            fiscal_year.tenant, "DCOM", fiscal_year.date_start.year
        )
        declaration.save(update_fields=["reference"])
    declaration.lines.all().delete()

    lines = (
        AccMoveLine.objects.filter(
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
            partner_id__isnull=False,
        )
        .values("partner_id", "account__account_class")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
    )

    total_amount = Decimal(0)
    dcom_lines: list[AccDcomLine] = []
    for entry in lines:
        debit = entry["total_debit"] or Decimal(0)
        credit = entry["total_credit"] or Decimal(0)
        amount = abs(debit - credit)
        if amount == 0:
            continue
        classification = _classification_for(entry["account__account_class"])
        partner_id = entry["partner_id"]
        assert partner_id is not None  # garanti par le filtre partner_id__isnull=False ci-dessus
        dcom_lines.append(
            AccDcomLine(
                tenant=fiscal_year.tenant,
                declaration=declaration,
                partner_id=partner_id,
                classification=classification,
                amount_mga=amount,
            )
        )
        total_amount += amount

    AccDcomLine.objects.bulk_create(dcom_lines)
    declaration.total_amount_mga = total_amount
    declaration.save(update_fields=["total_amount_mga"])
    return declaration
