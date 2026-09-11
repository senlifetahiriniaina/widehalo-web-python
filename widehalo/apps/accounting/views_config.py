"""Ecrans de configuration/master-data du module `accounting` (U3),
regroupes sous le hub "Parametres" plutot que sous le prefixe
transactionnel `/accounting/` (cf. decision de placement, plan Lot 2).
Une seule page liste+creation par entite simple, meme patron que
`apps.accounting.views` (formulaire simple, pas d'API ninja)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccPaymentTerm,
    AccPaymentTermLine,
    AccPeriod,
    AccTax,
    AccTenantDefaultAccount,
)
from apps.accounting.services.default_accounts import resolve_default_account
from apps.accounting.services.fiscal_years import (
    close_fiscal_year,
    closing_blockers,
    reopen_fiscal_year,
)
from apps.accounting.services.legal_mentions import mandatory_vat_mention
from apps.accounting.services.taxes import vat_applicable
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

PERIOD_COLUMNS = [
    Column(key="code", label="Code"),
    Column(key="date_start", label="Debut", searchable=False),
    Column(key="date_end", label="Fin", searchable=False),
    Column(key="state", label="Etat"),
]

JOURNAL_COLUMNS = [
    Column(key="code", label="Code"),
    Column(key="name", label="Libelle"),
    Column(key="type", label="Type"),
]

ACCOUNT_COLUMNS = [
    Column(key="code", label="Compte"),
    Column(key="name", label="Libelle"),
    Column(key="type", label="Type"),
]

TAX_COLUMNS = [
    Column(key="code", label="Code"),
    Column(key="name", label="Libelle"),
    # `AccTax` porte `rate`, jamais `rate_pct` — ce dernier appartient a
    # `AccIrcmDeclaration` et `AccLocalTax`. La colonne rendait donc une
    # cellule vide sur CHAQUE ligne, sous un en-tete qui promet un taux, et
    # son entete n'etait meme pas triable. Aucune erreur, aucune trace : le
    # filtre de rendu a un defaut a la chaine vide.
    Column(key="rate", label="Taux (%)", searchable=False),
]

#: `AccPaymentTerm` ne porte qu'un `name` : la colonne « Code » rendait une
#: cellule vide sur chaque ligne, et l'export un en-tete sans valeurs.
PAYMENT_TERM_COLUMNS = [
    Column(key="name", label="Libelle"),
]


@login_required
@screen_permission("accounting.view_accaccount")
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "accounting/config_index.html", {})


@login_required
@screen_permission("accounting.view_accfiscalyear")
def config_fiscal_years(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        # Clore ou rouvrir MODIFIE un exercice existant ; le cas par defaut
        # en CREE un. Deux verbes distincts, deux droits distincts.
        refus = screen_forbidden(
            request,
            "accounting.change_accfiscalyear"
            if request.POST.get("action", "create") in ("close", "reopen")
            else "accounting.add_accfiscalyear",
        )
        if refus is not None:
            return refus
        try:
            action = request.POST.get("action", "create")
            if action == "close":
                # T2 (ACC-10) — la clôture a enfin une surface. `AccFiscalYear.
                # state` etait AFFICHE par cet ecran (colonne « Statut ») et
                # ecrit par PERSONNE : un exercice ne pouvait pas etre clos,
                # et la colonne montrait « Ouvert » a perpetuite.
                close_fiscal_year(
                    get_object_or_404(
                        AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                    ),
                    by=cast(User, request.user),
                )
            elif action == "reopen":
                reopen_fiscal_year(
                    get_object_or_404(
                        AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                    ),
                    by=cast(User, request.user),
                    motif=request.POST.get("motif", ""),
                )
            else:
                AccFiscalYear.objects.create(
                    tenant=tenant,
                    code=request.POST.get("code", ""),
                    date_start=date.fromisoformat(request.POST.get("date_start", "")),
                    date_end=date.fromisoformat(request.POST.get("date_end", "")),
                )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)

    fiscal_years = list(AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"))
    # Ce qui empêche de clore, MONTRE avant que l'utilisateur ne clique —
    # decouvrir un blocage apres coup ferait recommencer la manoeuvre.
    for annee in fiscal_years:
        annee.blocages = (  # type: ignore[attr-defined]
            closing_blockers(annee) if annee.state == AccFiscalYear.STATE_OPEN else []
        )
    return render(
        request,
        "accounting/config_fiscal_years.html",
        {"fiscal_years": fiscal_years, "error": error},
    )


@login_required
@screen_permission("accounting.view_accperiod")
def config_periods(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    fiscal_years = AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start")
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accperiod")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            fiscal_year = fiscal_years.get(id=request.POST.get("fiscal_year_id"))
            AccPeriod.objects.create(
                tenant=tenant,
                fiscal_year=fiscal_year,
                code=request.POST.get("code", ""),
                date_start=date.fromisoformat(request.POST.get("date_start", "")),
                date_end=date.fromisoformat(request.POST.get("date_end", "")),
            )
        except AccFiscalYear.DoesNotExist:
            error = _("Exercice introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    default_fiscal_year = fiscal_years.first()
    return smart_table_response(
        request,
        table_key="accounting.periods",
        columns=PERIOD_COLUMNS,
        queryset=AccPeriod.objects.filter(tenant=tenant),
        page_template="accounting/config_periods.html",
        page_context={
            "fiscal_years": fiscal_years,
            "default_fiscal_year_id": default_fiscal_year.id if default_fiscal_year else None,
            "error": error,
        },
    )


@login_required
@screen_permission("accounting.view_accjournal")
def config_journals(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accjournal")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            default_account_id = request.POST.get("default_account_id") or None
            default_account = accounts.get(id=default_account_id) if default_account_id else None
            AccJournal.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                type=request.POST.get("type", AccJournal.TYPE_MISC),
                default_account=default_account,
                sequence_prefix=request.POST.get("sequence_prefix", ""),
                currency=request.POST.get("currency") or "MGA",
            )
        except AccAccount.DoesNotExist:
            error = _("Compte par défaut introuvable.")
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    return smart_table_response(
        request,
        table_key="accounting.journals",
        columns=JOURNAL_COLUMNS,
        queryset=AccJournal.objects.filter(tenant=tenant),
        page_template="accounting/config_journals.html",
        page_context={
            "accounts": accounts,
            "type_choices": AccJournal.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
@screen_permission("accounting.view_accaccount")
def config_accounts(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant).order_by("code")
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accaccount")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            parent_id = request.POST.get("parent_id") or None
            parent = accounts.get(id=parent_id) if parent_id else None
            AccAccount.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                account_class=int(request.POST.get("account_class") or 0),
                parent=parent,
                type=request.POST.get("type", AccAccount.TYPE_EXPENSE),
                reconcilable=bool(request.POST.get("reconcilable")),
                currency=request.POST.get("currency") or "MGA",
                analytic_required=bool(request.POST.get("analytic_required")),
            )
        except AccAccount.DoesNotExist:
            error = _("Compte parent introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    accounts = AccAccount.objects.filter(tenant=tenant).order_by("code")
    return smart_table_response(
        request,
        table_key="accounting.accounts",
        columns=ACCOUNT_COLUMNS,
        queryset=AccAccount.objects.filter(tenant=tenant),
        page_template="accounting/config_accounts.html",
        page_context={
            "type_choices": AccAccount.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
@screen_permission("accounting.view_acctenantdefaultaccount")
def config_default_accounts(request: HttpRequest) -> HttpResponse:
    """D10-2 — comptes par defaut du tenant (cahier §13.3, ecran « Plan de
    comptes » : « Comptes par defaut du tenant (vente, achat, TVA, client,
    fournisseur, banque, caisse) »).

    Sans cet ecran, le registre `AccTenantDefaultAccount` serait une table que
    rien ne peut remplir — le meme defaut que le dictionnaire d'indicateurs de
    la Phase 2, peuple nulle part hors des tests. L'ecran affiche donc aussi,
    pour chaque role non configure, le compte sur lequel le repli par type
    tomberait, afin que le choix implicite soit visible avant d'etre fige."""
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code")
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_acctenantdefaultaccount")
        if refus is not None:
            return refus

    if request.method == "POST":
        role = request.POST.get("role", "")
        account_id = request.POST.get("account_id") or None
        try:
            if account_id is None:
                AccTenantDefaultAccount.objects.filter(tenant=tenant, role=role).delete()
            else:
                account = accounts.get(id=account_id)
                AccTenantDefaultAccount.objects.update_or_create(
                    tenant=tenant, role=role, defaults={"account": account}
                )
        except AccAccount.DoesNotExist:
            error = _("Compte introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    configured = {
        entry.role: entry.account
        for entry in AccTenantDefaultAccount.objects.filter(tenant=tenant).select_related("account")
    }
    rows = []
    for role, label in AccTenantDefaultAccount.ROLE_CHOICES:
        account = configured.get(role)
        rows.append(
            {
                "role": role,
                "label": label,
                "account": account,
                # Ce que la resolution ferait aujourd'hui a defaut de
                # configuration : le repli par type, ordonne par code.
                "fallback": None if account is not None else resolve_default_account(tenant, role),
            }
        )

    return render(
        request,
        "accounting/config_default_accounts.html",
        {"rows": rows, "accounts": accounts, "error": error},
    )


@login_required
@screen_permission("accounting.view_accframework")
def config_fiscal(request: HttpRequest) -> HttpResponse:
    """L17 — l'ecran de configuration fiscale que le produit promettait.

    **Trois champs joignables uniquement par `/admin/` jusqu'ici.**
    `Tenant.fiscal_regime`, `Tenant.vat_opted_in` et `Tenant.legal_mentions`
    n'etaient ecrits par AUCUNE surface du produit : ni l'onboarding, ni
    `create_tenant`, ni `apply_country_defaults`, ni l'ecran « Profil de
    l'entreprise » (qui ne traite qu'adresse, telephone, e-mail et logo).
    Consequence : **tout tenant nait `reel_avec_tva`**, y compris une
    entreprise a l'impot synthetique, et la seule facon de le corriger
    passait par le formulaire d'administration Django, reserve au
    superutilisateur.

    La docstring de `vat_opted_in` annonce depuis l'origine « un futur ecran
    de configuration fiscale (module accounting) [pour] guider ce choix
    une fois le CA reel connu ». C'est celui-ci.

    **Il SIGNALE, il ne decide jamais.** Le chiffre d'affaires reel est
    affiche face au seuil d'assujettissement, et un ecart est nomme — mais
    le regime n'est jamais change d'office. Un basculement automatique
    reecrirait la qualification fiscale d'une societe sur la foi d'un
    agregat interne, alors que le regime resulte d'une declaration a
    l'administration : c'est au comptable de trancher, avec le chiffre sous
    les yeux."""
    tenant = resolve_tenant(request)
    error = None
    saved = False

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accframework")
        if refus is not None:
            return refus

    if request.method == "POST":
        regime = request.POST.get("fiscal_regime", "")
        if regime not in dict(Tenant.FISCAL_REGIME_CHOICES):
            error = _("Régime fiscal inconnu.")
        else:
            tenant.fiscal_regime = regime
            tenant.vat_opted_in = bool(request.POST.get("vat_opted_in"))
            tenant.legal_mentions = request.POST.get("legal_mentions", "")
            tenant.save(update_fields=["fiscal_regime", "vat_opted_in", "legal_mentions"])
            saved = True

    return render(
        request,
        "accounting/config_fiscal.html",
        {
            "tenant": tenant,
            "regime_choices": Tenant.FISCAL_REGIME_CHOICES,
            "is_vat_liable": vat_applicable(tenant),
            "mandatory_vat_mention": mandatory_vat_mention(tenant),
            "error": error,
            "saved": saved,
            **_vat_threshold_context(tenant),
        },
    )


def _vat_threshold_context(tenant: Tenant) -> dict[str, object]:
    """Chiffre d'affaires reel face au seuil legal — ou rien du tout.

    Trois choses peuvent manquer, et aucune n'est une erreur : le parametre
    `tva.seuil_assujettissement` (une instance dont les migrations n'ont pas
    ete rejouees), le chiffre d'affaires (un tenant neuf), ou les deux. Dans
    ces cas l'ecran reste utilisable et se contente de ne rien affirmer —
    afficher « CA : 0 Ar, en dessous du seuil » a un tenant qui n'a
    simplement rien saisi serait une conclusion tiree du vide."""
    from apps.accounting.services.vat_reference import (
        resolve_export_vat_rate,
        resolve_vat_liability_thresholds,
    )

    # T2 (ACC-9) — le taux d'export est AFFICHE ici, et nulle part ailleurs.
    # C'etait un parametre reglementaire seme et lu par personne ; cet ecran
    # est son seul lecteur de production, et le bon : le comptable qui
    # parametre le regime a besoin de savoir ce que le produit connait du
    # taux d'export, et de voir qu'il n'est pas encore valide. Il n'est
    # applique a AUCUN calcul — cf. `resolve_export_vat_rate` pour le motif
    # complet.
    taux_export = resolve_export_vat_rate(tenant)

    thresholds = resolve_vat_liability_thresholds(tenant)
    if thresholds is None:
        return {
            "vat_thresholds": None,
            "annual_revenue_mga": None,
            "regime_hint": "",
            "export_vat_rate": taux_export,
        }

    revenue = _trailing_year_revenue(tenant)
    hint = ""
    if revenue is not None:
        seuil, plancher = thresholds["seuil_mga"], thresholds["plancher_option_mga"]
        if revenue >= seuil and tenant.fiscal_regime != Tenant.FISCAL_REGIME_REAL_WITH_VAT:
            hint = _(
                "Le chiffre d'affaires des douze derniers mois dépasse le seuil "
                "d'assujettissement : le régime déclaré ne correspond peut-être plus."
            )
        elif plancher <= revenue < seuil and not tenant.vat_opted_in:
            hint = _(
                "Le chiffre d'affaires se situe dans la tranche où l'assujettissement "
                "à la TVA est optionnel (Loi de finances 2026) : l'option n'est pas exercée."
            )
        elif revenue < plancher and tenant.fiscal_regime != Tenant.FISCAL_REGIME_SYNTHETIC:
            hint = _(
                "Le chiffre d'affaires est inférieur au plancher : le régime de l'impôt "
                "synthétique pourrait s'appliquer."
            )
    return {
        "vat_thresholds": thresholds,
        "annual_revenue_mga": revenue,
        "regime_hint": hint,
        "export_vat_rate": taux_export,
    }


def _trailing_year_revenue(tenant: Tenant) -> Decimal | None:
    """Chiffre d'affaires des douze derniers mois, LU DANS LES LIVRES.

    Somme des credits nets des comptes de PRODUIT sur les ecritures
    publiees. Deux raisons de le prendre ici plutot que dans `sales` :

    - **la regle de couplage n1 l'impose** : `accounting` ne peut pas
      dependre de `sales`, qui est en aval. Le garde-fou
      `test_module_boundaries` a d'ailleurs refuse le premier jet de cet
      ecran, qui appelait `sales.services.public.get_revenue_summary` ;
    - **c'est le bon chiffre** : un seuil d'assujettissement se compare au
      chiffre d'affaires COMPTABLE, celui que l'administration lira dans la
      liasse — pas au cumul des commandes du module de vente, qui inclut
      des documents non encore factures et exclut tout produit qui n'est
      pas passe par `sales` (facturation projet, refacturation de fret,
      caisse).

    Meme forme de calcul que `public.get_stock_account_balance` : etat
    `posted` uniquement, `debit`/`credit` nets, jamais un champ
    denormalise.

    `None` — et non `Decimal(0)` — quand aucune ecriture de produit
    n'existe : « aucune vente enregistree » et « un chiffre d'affaires
    nul » n'appellent pas le meme commentaire a l'ecran, et le second
    serait une conclusion tiree du vide sur un tenant qui vient d'etre
    cree."""
    from datetime import timedelta

    from django.db.models import Sum
    from django.utils import timezone

    from apps.accounting.models import AccMove, AccMoveLine

    today = timezone.now().date()
    aggregate = AccMoveLine.objects.filter(
        tenant=tenant,
        account__type=AccAccount.TYPE_INCOME,
        move__state=AccMove.STATE_POSTED,
        move__date__gte=today - timedelta(days=365),
        move__date__lte=today,
    ).aggregate(credit=Sum("credit"), debit=Sum("debit"))
    if aggregate["credit"] is None and aggregate["debit"] is None:
        return None
    revenue = (aggregate["credit"] or Decimal(0)) - (aggregate["debit"] or Decimal(0))
    return revenue


@login_required
@screen_permission("accounting.view_acctax")
def config_taxes(request: HttpRequest) -> HttpResponse:
    """Ecran de parametrage des taxes.

    **Volet « proposee » de RG-ACC-5, ferme ici (bloquants 4/4).** La regle
    dit « sur un tenant au regime synthetique, aucune AccTax n'est PROPOSEE
    ni APPLIQUEE ». Seul le volet « appliquee » etait tenu, et uniquement
    par trois surfaces de LECTURE (`applicable_taxes`,
    `public.get_default_sale_tax`, `public.get_sale_tax`). Cet ecran, lui,
    creait une `AccTax` sur un tenant non assujetti sans le moindre
    avertissement — et le modele ne porte la regle qu'en commentaire, sans
    `clean()` ni contrainte. Un tenant synthetique pouvait donc se
    constituer un jeu de taxes que le produit refuserait ensuite
    d'appliquer : une configuration sans effet, et rien pour le dire.

    Le refus est cote POST, jamais seulement dans le gabarit : masquer un
    formulaire n'empeche personne de poster.

    Les taxes DEJA enregistrees restent affichees, avec la banniere de
    non-assujettissement. Les faire disparaitre d'un ecran de configuration
    ressemblerait a une perte de donnees, alors qu'elles existent bel et
    bien en base — elles ne sont simplement jamais appliquees."""
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True)
    is_vat_liable = vat_applicable(tenant)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_acctax")
        if refus is not None:
            return refus

    if request.method == "POST" and not is_vat_liable:
        error = _(
            "Ce tenant n'est pas assujetti à la TVA : aucune taxe ne peut être "
            "enregistrée (RG-ACC-5). Le régime se change à l'écran de configuration "
            "fiscale."
        )
    elif request.method == "POST":
        try:
            collected_id = request.POST.get("account_collected_id") or None
            deductible_id = request.POST.get("account_deductible_id") or None
            AccTax.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                type=request.POST.get("type", AccTax.TYPE_SALE),
                rate=Decimal(request.POST.get("rate") or "0"),
                is_included=bool(request.POST.get("is_included")),
                account_collected=accounts.get(id=collected_id) if collected_id else None,
                account_deductible=accounts.get(id=deductible_id) if deductible_id else None,
                valid_from=(
                    date.fromisoformat(request.POST["valid_from"])
                    if request.POST.get("valid_from")
                    else None
                ),
                valid_to=(
                    date.fromisoformat(request.POST["valid_to"])
                    if request.POST.get("valid_to")
                    else None
                ),
            )
        except AccAccount.DoesNotExist:
            error = _("Compte introuvable.")
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    return smart_table_response(
        request,
        table_key="accounting.taxes",
        columns=TAX_COLUMNS,
        queryset=AccTax.objects.filter(tenant=tenant),
        page_template="accounting/config_taxes.html",
        page_context={
            "accounts": accounts,
            "type_choices": AccTax.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
@screen_permission("accounting.view_accpaymentterm")
def config_payment_terms(request: HttpRequest) -> HttpResponse:
    """Formulaire minimal : une condition de paiement creee avec une seule
    ligne (le multi-lignes reste accessible via l'API pour les besoins
    avances — meme simplification que `apps.accounting.views::invoice_create`)."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accpaymentterm")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            value_type = request.POST.get("value_type", AccPaymentTermLine.VALUE_TYPE_BALANCE)
            raw_value = request.POST.get("value", "").strip()
            if value_type == AccPaymentTermLine.VALUE_TYPE_BALANCE:
                value = None
            else:
                if not raw_value:
                    raise ValidationError(
                        _("Une valeur (pourcentage ou montant) est requise pour ce type.")
                    )
                value = Decimal(raw_value)
            term = AccPaymentTerm.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
            )
            AccPaymentTermLine.objects.create(
                tenant=tenant,
                term=term,
                sequence=0,
                value_type=value_type,
                value=value,
                days=int(request.POST.get("days") or 0),
            )
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    return smart_table_response(
        request,
        table_key="accounting.payment_terms",
        columns=PAYMENT_TERM_COLUMNS,
        queryset=AccPaymentTerm.objects.filter(tenant=tenant).prefetch_related("lines"),
        page_template="accounting/config_payment_terms.html",
        page_context={
            "value_type_choices": AccPaymentTermLine.VALUE_TYPE_CHOICES,
            "error": error,
        },
    )
