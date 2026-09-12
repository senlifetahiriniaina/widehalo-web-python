"""G-2 — le patrimoine : immobilisations, amortissements, provisions.

**Ce que la mesure a trouve, et pourquoi cet ecran existe.** `services/
assets.py` sait inscrire une immobilisation, calculer son plan
d'amortissement lineaire au prorata des jours de detention, poster la
dotation au grand livre, ceder l'actif et enregistrer le mouvement d'une
provision. Tout cela est livre, teste, et documente jusqu'a sa reserve
OECFM. Et **aucun ecran n'existait** : `AccAsset`, `AccAssetMovement`,
`AccAssetDepreciation` et `AccProvision` n'apparaissaient nulle part dans
`templates/`. Un exploitant devant un navigateur ne pouvait pas inscrire
une seule immobilisation — alors que l'annexe fiscale ACC-ANNEXE1 qui les
consomme, elle, etait deja produite.

C'est le motif « rien de decoratif » a l'echelle d'un pan du module : la
capacite existe, la porte n'existe pas.

**La dotation ne se poste jamais par accident.** `compute_annual_
depreciation` distingue le CALCUL (par defaut, `move=None`) de sa
COMPTABILISATION (`post=True`, qui exige journal, periode et les deux
comptes). L'ecran reprend exactement cette distinction en deux boutons
separes plutot qu'en une case a cocher : un plan d'amortissement se relit
avant d'etre engage au grand livre, et c'est la pratique que la docstring
du service defend.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    AccAccount,
    AccAsset,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
    AccProvision,
)
from apps.accounting.services.assets import (
    compute_annual_depreciation,
    dispose_asset,
    record_provision_movement,
    register_asset,
)
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

ASSET_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="label", label=_("Libellé")),
    Column(key="category", label=_("Catégorie")),
    Column(key="acquisition_date", label=_("Acquise le"), searchable=False),
    Column(
        key="acquisition_value_mga", label=_("Valeur d'acquisition"), searchable=False, format="mga"
    ),
    Column(key="state", label=_("État")),
]

PROVISION_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="nature", label=_("Nature")),
    Column(key="fiscal_year", label=_("Exercice"), search_key="fiscal_year__code"),
    Column(key="opening_amount_mga", label=_("À l'ouverture"), searchable=False, format="mga"),
    Column(key="dotation_mga", label=_("Dotation"), searchable=False, format="mga"),
    Column(key="reprise_mga", label=_("Reprise"), searchable=False, format="mga"),
    Column(key="closing_amount_mga", label=_("À la clôture"), searchable=False, format="mga"),
]


def _montant(brut: str | None, *, defaut: str = "0") -> Decimal:
    """Un montant mal saisi devient un refus lisible, jamais un 500.

    `Decimal("")` leve `InvalidOperation`, qu'aucun gestionnaire de ce depot
    ne rattrape — c'est exactement la famille de defaut que T4bis a fermee
    sur les identifiants, et elle se reproduit a l'identique sur les
    montants d'un formulaire."""
    try:
        return Decimal((brut or defaut).replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(_("Montant illisible : %(v)s") % {"v": brut}) from exc


def _entier(brut: str | None, *, defaut: str = "0") -> int:
    try:
        return int(brut or defaut)
    except (TypeError, ValueError) as exc:
        raise ValidationError(_("Nombre illisible : %(v)s") % {"v": brut}) from exc


def _date(brut: str | None) -> date:
    try:
        return date.fromisoformat(brut or "")
    except ValueError as exc:
        raise ValidationError(_("Date illisible : %(v)s") % {"v": brut}) from exc


@login_required
@screen_permission("accounting.view_accasset")
def asset_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    comptes = list(AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"))
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accasset")
        if refus is not None:
            return refus
        try:
            asset = register_asset(
                tenant=tenant,
                category=request.POST.get("category", AccAsset.CATEGORY_CORPORELLE),
                label=request.POST.get("label", ""),
                account=get_object_or_404(
                    AccAccount, id=request.POST.get("account_id"), tenant=tenant
                ),
                acquisition_date=_date(request.POST.get("acquisition_date")),
                acquisition_value_mga=_montant(request.POST.get("acquisition_value_mga")),
                # Le jeu ferme du modele porte deux methodes ; le service en
                # refuse une explicitement. L'ecran ne propose donc que
                # celle qui existe, plutot que de laisser choisir une voie
                # qui sera refusee a l'envoi (meme regle qu'en C-1d).
                depreciation_method=AccAsset.METHOD_LINEAIRE,
                useful_life_years=_entier(request.POST.get("useful_life_years"), defaut="1"),
                residual_value_mga=_montant(request.POST.get("residual_value_mga")),
            )
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            return redirect("accounting:asset_detail", asset_id=asset.id)

    return smart_table_response(
        request,
        table_key="accounting.assets",
        columns=ASSET_COLUMNS,
        queryset=AccAsset.objects.filter(tenant=tenant).select_related("account"),
        page_template="accounting/assets.html",
        page_context={
            "row_url_name": "accounting:asset_detail",
            "comptes": comptes,
            "categories": AccAsset.CATEGORY_CHOICES,
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_accasset")
def asset_detail(request: HttpRequest, asset_id: Any) -> HttpResponse:
    tenant = resolve_tenant(request)
    asset = get_object_or_404(AccAsset, id=asset_id, tenant=tenant)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accasset")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "dispose":
                dispose_asset(
                    asset,
                    disposal_date=_date(request.POST.get("disposal_date")),
                    disposal_value_mga=_montant(request.POST.get("disposal_value_mga")),
                )
            elif action in ("depreciate", "depreciate_and_post"):
                exercice = get_object_or_404(
                    AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                )
                poster = action == "depreciate_and_post"
                compute_annual_depreciation(
                    asset,
                    exercice,
                    post=poster,
                    journal=(
                        get_object_or_404(
                            AccJournal, id=request.POST.get("journal_id"), tenant=tenant
                        )
                        if poster
                        else None
                    ),
                    period=(
                        get_object_or_404(
                            AccPeriod, id=request.POST.get("period_id"), fiscal_year=exercice
                        )
                        if poster
                        else None
                    ),
                    dotation_account=(
                        get_object_or_404(
                            AccAccount, id=request.POST.get("dotation_account_id"), tenant=tenant
                        )
                        if poster
                        else None
                    ),
                    accumulated_depreciation_account=(
                        get_object_or_404(
                            AccAccount,
                            id=request.POST.get("accumulated_account_id"),
                            tenant=tenant,
                        )
                        if poster
                        else None
                    ),
                )
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            return redirect("accounting:asset_detail", asset_id=asset.id)

    exercices = list(AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"))
    return render(
        request,
        "accounting/asset_detail.html",
        {
            "asset": asset,
            "mouvements": asset.movements.order_by("date"),
            "annuites": asset.depreciation_entries.select_related("fiscal_year", "move").order_by(
                "fiscal_year__date_start"
            ),
            "exercices": exercices,
            "journaux": AccJournal.objects.filter(tenant=tenant).order_by("code"),
            "periodes": AccPeriod.objects.filter(fiscal_year__tenant=tenant).order_by("code"),
            "comptes": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_accprovision")
def provision_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accprovision")
        if refus is not None:
            return refus
        try:
            record_provision_movement(
                tenant=tenant,
                nature=request.POST.get("nature", ""),
                account=get_object_or_404(
                    AccAccount, id=request.POST.get("account_id"), tenant=tenant
                ),
                fiscal_year=get_object_or_404(
                    AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                ),
                opening_amount_mga=_montant(request.POST.get("opening_amount_mga")),
                dotation_mga=_montant(request.POST.get("dotation_mga")),
                reprise_mga=_montant(request.POST.get("reprise_mga")),
            )
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            return redirect("accounting:provisions")

    return smart_table_response(
        request,
        table_key="accounting.provisions",
        columns=PROVISION_COLUMNS,
        queryset=AccProvision.objects.filter(tenant=tenant).select_related(
            "account", "fiscal_year"
        ),
        page_template="accounting/provisions.html",
        page_context={
            "comptes": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "exercices": AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"),
            "error": erreur,
        },
    )
