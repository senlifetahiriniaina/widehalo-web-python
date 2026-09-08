"""ACC-6 — établir la déclaration de TVA d'une période, et la rapprocher.

**Le critère, mot pour mot** : « La déclaration de TVA d'une période se
rapproche à l'ariary près de la somme des écritures de TVA de la période,
avec un état justificatif ligne à ligne. »

**Ce qui existait avant ce lot : rien**, et le dépôt l'écrivait lui-même.
`services/fiscal_export.py` disait, à la ligne ACC-TVA de son registre :
« Aucune déclaration TVA dédiée (pas de modèle `acc_vat_declaration` à ce
stade) : approche via `trial_balance`/`general_ledger` filtrés sur les
comptes de TVA collectée/déductible ». L'audit classait ACC-6 « le service
de déclaration existe, le rapprochement n'a pas été vérifié » ; la mesure
dit autre chose — il n'y avait ni objet à rapprocher, ni état justificatif.

**Le rapprochement, et pourquoi il ne peut pas être un simple booléen.**
Deux côtés sont comparés :

- la **déclaration**, établie depuis les lignes d'écritures publiées qui
  DÉSIGNENT une taxe (`AccMoveLine.tax`), avec leur base (`tax_base`) ;
- les **livres**, c'est-à-dire le mouvement net des comptes de TVA de ces
  mêmes taxes (`AccTax.account_collected` / `account_deductible`).

Ils diffèrent dès qu'une écriture manuelle touche un compte de TVA sans
désigner de taxe — un rappel, une régularisation, un complément. C'est
parfaitement légal, et l'écart mesure exactement ce qu'il reste à
justifier. Le conserver dans la déclaration (`ecart_mga`) est ce qui permet
de le retrouver ; le recalculer silencieusement à chaque affichage
transformerait un écart traçable en surprise.

**Seules les écritures PUBLIÉES comptent.** Un brouillon n'est pas une
écriture : le déclarer reviendrait à déclarer une intention. C'est aussi
ce qui rend la déclaration reproductible — les lignes publiées sont
immuables par déclencheur de base (`acc_move_immutable_when_posted`), donc
un état justificatif régénéré rend exactement les mêmes lignes.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccMove,
    AccMoveLine,
    AccPeriod,
    AccTax,
    AccVatDeclaration,
    AccVatDeclarationLine,
)

#: Le quantum des colonnes de montant de ce module.
QUANT = Decimal("0.0001")

#: Le sens de chaque type de taxe. Une taxe de VENTE collecte, une taxe
#: d'ACHAT ouvre droit à déduction — la correspondance est celle du PCG et
#: n'a rien de configurable, d'où une table plutôt qu'un champ.
SENS_PAR_TYPE: dict[str, str] = {
    AccTax.TYPE_SALE: AccVatDeclarationLine.SENS_COLLECTED,
    AccTax.TYPE_PURCHASE: AccVatDeclarationLine.SENS_DEDUCTIBLE,
}


def _taxes_of_period(period: AccPeriod) -> list[AccTax]:
    """Les taxes valides sur la période — bornes de validité comprises.

    Une taxe dont la validité s'arrête au milieu de la période reste
    concernée : elle a produit des écritures sur sa partie valide, et les
    omettre creuserait un écart que personne ne saurait expliquer."""
    return list(
        AccTax.objects.filter(tenant=period.tenant)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=period.date_end))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=period.date_start))
        .select_related("account_collected", "account_deductible")
        .order_by("type", "code")
    )


def _posted_lines_of_period(period: AccPeriod) -> QuerySet[AccMoveLine]:
    return AccMoveLine.objects.filter(move__period=period, move__state=AccMove.STATE_POSTED)


def _tax_account_of(tax: AccTax) -> Any:
    sens = SENS_PAR_TYPE.get(tax.type)
    if sens == AccVatDeclarationLine.SENS_COLLECTED:
        return tax.account_collected
    return tax.account_deductible


def _books_movement(period: AccPeriod, tax: AccTax) -> Decimal:
    """Le mouvement NET du compte de TVA de cette taxe, dans le sens où la
    TVA s'y accumule.

    La TVA collectée est au CRÉDIT d'un compte de dette (445 collectée), la
    déductible au DÉBIT d'un compte de créance. Prendre la valeur absolue
    masquerait une écriture passée à l'envers — précisément le genre
    d'erreur que ce rapprochement existe pour attraper."""
    compte = _tax_account_of(tax)
    if compte is None:
        return Decimal(0)
    totaux = (
        _posted_lines_of_period(period)
        .filter(account=compte)
        .aggregate(debit=Sum("debit"), credit=Sum("credit"))
    )
    debit = totaux["debit"] or Decimal(0)
    credit = totaux["credit"] or Decimal(0)
    if SENS_PAR_TYPE.get(tax.type) == AccVatDeclarationLine.SENS_COLLECTED:
        return (credit - debit).quantize(QUANT)
    return (debit - credit).quantize(QUANT)


def _declared_amounts(period: AccPeriod, tax: AccTax) -> tuple[Decimal, Decimal, int]:
    """`(base, tva, nombre de lignes)` déclarés pour cette taxe.

    La TVA est relue depuis les MONTANTS des lignes, jamais recalculée
    depuis la base et le taux : une facture émise sous un taux qui a changé
    depuis doit se déclarer au taux qu'elle porte. Recalculer réécrirait
    l'histoire."""
    lignes = _posted_lines_of_period(period).filter(tax=tax)
    totaux = lignes.aggregate(base=Sum("tax_base"), debit=Sum("debit"), credit=Sum("credit"))
    base = (totaux["base"] or Decimal(0)).quantize(QUANT)
    debit = totaux["debit"] or Decimal(0)
    credit = totaux["credit"] or Decimal(0)
    if SENS_PAR_TYPE.get(tax.type) == AccVatDeclarationLine.SENS_COLLECTED:
        montant = (credit - debit).quantize(QUANT)
    else:
        montant = (debit - credit).quantize(QUANT)
    return base, montant, lignes.count()


@transaction.atomic
def build_vat_declaration(period: AccPeriod) -> AccVatDeclaration:
    """Établit (ou ré-établit) la déclaration de TVA d'une période.

    Idempotente sur la période : rejouer la génération remplace les lignes
    plutôt que de les empiler. Une déclaration DÉPOSÉE, elle, ne se
    régénère pas — ce qui a été transmis à l'administration ne se réécrit
    pas parce qu'une écriture a bougé depuis."""
    declaration, _cree = AccVatDeclaration.objects.get_or_create(
        tenant=period.tenant, period=period
    )
    if declaration.state == AccVatDeclaration.STATE_FILED:
        raise ValidationError(
            _(
                "La déclaration de TVA de « %(periode)s » est déposée : elle ne "
                "se régénère pas. Ce qui a été transmis à l'administration ne "
                "se réécrit pas parce qu'une écriture a bougé depuis."
            )
            % {"periode": period.code}
        )

    declaration.lines.all().delete()

    collecte = deductible = Decimal(0)
    collecte_livres = deductible_livres = Decimal(0)

    for tax in _taxes_of_period(period):
        sens = SENS_PAR_TYPE.get(tax.type)
        if sens is None:
            continue
        base, montant, nombre = _declared_amounts(period, tax)
        livres = _books_movement(period, tax)
        if not base and not montant and not livres and not nombre:
            # Une taxe sans le moindre mouvement n'a rien à justifier : la
            # porter alignerait des lignes à zéro sur un état dont l'objet
            # est précisément d'être lu.
            continue

        AccVatDeclarationLine.objects.create(
            tenant=period.tenant,
            declaration=declaration,
            tax=tax,
            sens=sens,
            base_mga=base,
            tax_mga=montant,
            books_mga=livres,
            move_line_count=nombre,
        )
        if sens == AccVatDeclarationLine.SENS_COLLECTED:
            collecte += montant
            collecte_livres += livres
        else:
            deductible += montant
            deductible_livres += livres

    declaration.collected_mga = collecte
    declaration.deductible_mga = deductible
    declaration.net_mga = collecte - deductible
    declaration.collected_books_mga = collecte_livres
    declaration.deductible_books_mga = deductible_livres
    # L'écart porte sur les DEUX sens, additionnés dans le sens où ils
    # pèsent sur le net : une collecte manquante et une déduction
    # excédentaire creusent l'écart dans le même sens.
    declaration.ecart_mga = (collecte - collecte_livres) - (deductible - deductible_livres)
    declaration.generated_at = timezone.now()
    declaration.save()
    return declaration


def file_vat_declaration(declaration: AccVatDeclaration) -> AccVatDeclaration:
    """Marque la déclaration comme déposée — et refuse si elle ne se
    rapproche pas.

    C'est la moitié opérante du critère. Une déclaration qu'on dépose sans
    qu'elle tombe juste transmet à l'administration un montant que les
    livres ne justifient pas ; le refus force à traiter l'écart, en le
    NOMMANT, plutôt qu'à le découvrir au contrôle."""
    if declaration.state == AccVatDeclaration.STATE_FILED:
        raise ValidationError(_("Cette déclaration est déjà déposée."))
    if not declaration.is_reconciled:
        raise ValidationError(
            _(
                "Écart de %(ecart)s Ar entre la déclaration et les livres : "
                "dépôt refusé. Le détail ligne à ligne désigne la ou les taxes "
                "concernées."
            )
            % {"ecart": declaration.ecart_mga}
        )
    declaration.state = AccVatDeclaration.STATE_FILED
    declaration.save(update_fields=["state"])
    return declaration


def vat_declaration_detail(declaration: AccVatDeclaration) -> list[dict[str, Any]]:
    """L'état justificatif LIGNE À LIGNE, au sens fort : une ligne
    d'écriture par ligne d'état.

    Recalculé depuis les lignes publiées plutôt que stocké : elles sont
    immuables par déclencheur de base, si bien qu'un état régénéré rend
    exactement les mêmes lignes. Les figer dupliquerait une donnée déjà
    inaltérable et créerait deux vérités à faire diverger."""
    period = declaration.period
    lignes = (
        _posted_lines_of_period(period)
        .filter(tax__isnull=False)
        .select_related("move", "account", "tax")
        .order_by("move__date", "move__reference", "created_at")
    )
    return [
        {
            "date": ligne.move.date,
            "reference": ligne.move.reference,
            "libelle": ligne.label,
            "taxe": ligne.tax.code if ligne.tax else "",
            "sens": SENS_PAR_TYPE.get(ligne.tax.type, "") if ligne.tax else "",
            "base_mga": ligne.tax_base or Decimal(0),
            "debit_mga": ligne.debit,
            "credit_mga": ligne.credit,
            # §9.2 : la CLASSE, jamais le numero complet — meme regle que la
            # projection de sortie du hub de flux.
            "classe_pcg": str(ligne.account.account_class),
        }
        for ligne in lignes
    ]


def unjustified_book_lines(declaration: AccVatDeclaration) -> list[dict[str, Any]]:
    """Les lignes qui creusent l'écart : elles touchent un compte de TVA
    sans désigner de taxe.

    C'est la réponse à « d'où vient l'écart ? », et c'est ce qui distingue
    un rapprochement d'un simple constat de différence. Sans cette liste,
    `ecart_mga` dirait qu'il manque quelque chose sans dire où chercher."""
    comptes = {
        compte.id
        for tax in _taxes_of_period(declaration.period)
        if (compte := _tax_account_of(tax)) is not None
    }
    if not comptes:
        return []
    lignes = (
        _posted_lines_of_period(declaration.period)
        .filter(account_id__in=comptes, tax__isnull=True)
        .select_related("move", "account")
        .order_by("move__date", "move__reference")
    )
    return [
        {
            "date": ligne.move.date,
            "reference": ligne.move.reference,
            "libelle": ligne.label,
            "debit_mga": ligne.debit,
            "credit_mga": ligne.credit,
            "classe_pcg": str(ligne.account.account_class),
        }
        for ligne in lignes
    ]


def declaration_for(period: AccPeriod, *, at_date: dt.date | None = None) -> AccVatDeclaration:
    """Raccourci de lecture pour les écrans : la déclaration de la période,
    établie si elle ne l'est pas encore."""
    existante = AccVatDeclaration.objects.filter(tenant=period.tenant, period=period).first()
    if existante is not None and existante.state == AccVatDeclaration.STATE_FILED:
        return existante
    return build_vat_declaration(period)
