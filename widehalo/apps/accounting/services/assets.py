"""A10 (Phase 2 `accounting`) : immobilisations, amortissements, provisions —
briques source de l'annexe composite ACC-ANNEXE1 (§1.11 du document annexe
« Rapports_Financiers_Fiscaux_et_Bancaires_Madagascar.pdf »,
`services/reports.py::fixed_asset_annexes`).

Reserve OECFM (meme discipline que `chart_of_accounts.py`/`reports.py`) : la
structure des annexes fiscales qui consomment ces entites n'est pas verifiee
sur un formulaire officiel numerote malgache (§3.5 du document annexe) — a
confirmer aupres d'un cabinet OECFM avant tout usage en production reelle.

**Frontiere de stub assumee (meme discipline que `sales` S3/S6)** : ni
`register_asset` (acquisition) ni `record_provision_movement` ne postent
d'ecriture reelle par defaut — `purchase` n'existe pas encore, et
l'acquisition d'une immobilisation est normalement deja comptabilisee par le
flux d'achat/paiement qui l'a financee ; cette fonction se contente
d'enregistrer l'EXISTENCE de l'immobilisation/provision pour les besoins de
calcul d'amortissement et de reporting annexe. Seule
`compute_annual_depreciation` peut, sur demande explicite (`post=True`),
poster une ecriture reelle de dotation — un tenant doit pouvoir
calculer/relire un plan d'amortissement avant de l'engager au grand livre,
pratique comptable standard."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccAsset,
    AccAssetDepreciation,
    AccAssetMovement,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
    AccProvision,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference

_QUANT = Decimal("0.0001")


def register_asset(
    *,
    tenant: Tenant,
    category: str,
    label: str,
    account: AccAccount,
    acquisition_date: Any,
    acquisition_value_mga: Decimal,
    depreciation_method: str,
    useful_life_years: int,
    residual_value_mga: Decimal = Decimal(0),
) -> AccAsset:
    """Enregistre une immobilisation en `state="active"` et son mouvement
    d'acquisition (`AccAssetMovement`, `move=None` — cf. docstring de module).

    V1 limitation explicite : `depreciation_method="degressif"` est refuse
    (`ValidationError`) — seule la methode lineaire est implementee (cf.
    `compute_annual_depreciation`), meme philosophie "explicabilite d'abord"
    que RG-SAL-8 : ne jamais calculer silencieusement un amortissement
    degressif approximatif sans l'avoir reellement implemente."""
    if depreciation_method == AccAsset.METHOD_DEGRESSIF:
        raise ValidationError(
            _(
                "Methode d'amortissement degressive non implementee en V1 : "
                "seule la methode lineaire est disponible."
            )
        )
    if depreciation_method != AccAsset.METHOD_LINEAIRE:
        raise ValidationError(
            _("Methode d'amortissement inconnue : %(m)s") % {"m": depreciation_method}
        )

    reference = next_reference(tenant, "IMMO", acquisition_date.year)
    asset = AccAsset.objects.create(
        tenant=tenant,
        reference=reference,
        category=category,
        label=label,
        account=account,
        acquisition_date=acquisition_date,
        acquisition_value_mga=acquisition_value_mga,
        depreciation_method=depreciation_method,
        useful_life_years=useful_life_years,
        residual_value_mga=residual_value_mga,
        state=AccAsset.STATE_ACTIVE,
    )
    AccAssetMovement.objects.create(
        tenant=tenant,
        asset=asset,
        movement_type=AccAssetMovement.MOVEMENT_ACQUISITION,
        date=acquisition_date,
        amount_mga=acquisition_value_mga,
        move=None,
    )
    return asset


def dispose_asset(asset: AccAsset, *, disposal_date: Any, disposal_value_mga: Decimal) -> AccAsset:
    """Cede/met au rebut une immobilisation active. Garde contre une double
    cession (`ValidationError`) — pas de FSM pour 2 etats sans autre garde,
    verifiee ici directement plutot que via `django-fsm`."""
    if asset.state == AccAsset.STATE_DISPOSED:
        raise ValidationError(_("Cette immobilisation est deja cedee/mise au rebut."))

    asset.disposal_date = disposal_date
    asset.disposal_value_mga = disposal_value_mga
    asset.state = AccAsset.STATE_DISPOSED
    asset.save(update_fields=["disposal_date", "disposal_value_mga", "state"])

    AccAssetMovement.objects.create(
        tenant=asset.tenant,
        asset=asset,
        movement_type=AccAssetMovement.MOVEMENT_DISPOSAL,
        date=disposal_date,
        amount_mga=disposal_value_mga,
        move=None,
    )
    return asset


def _prior_depreciation(asset: AccAsset, fiscal_year: AccFiscalYear) -> AccAssetDepreciation | None:
    """La derniere annuite calculee pour `asset` sur un exercice STRICTEMENT
    anterieur a `fiscal_year` (meme convention d'"exercice precedent" que
    `reports.py::equity_variation_statement` — le plus recent exercice dont
    `date_end < fiscal_year.date_start`)."""
    return (
        AccAssetDepreciation.objects.filter(
            asset=asset, fiscal_year__date_end__lt=fiscal_year.date_start
        )
        .order_by("-fiscal_year__date_end")
        .first()
    )


def compute_annual_depreciation(
    asset: AccAsset,
    fiscal_year: AccFiscalYear,
    *,
    post: bool = False,
    journal: AccJournal | None = None,
    period: AccPeriod | None = None,
    dotation_account: AccAccount | None = None,
    accumulated_depreciation_account: AccAccount | None = None,
) -> AccAssetDepreciation:
    """Calcule (et enregistre) l'annuite d'amortissement lineaire de `asset`
    pour `fiscal_year`.

    Methode de proration EXACTE retenue (a documenter/confirmer aupres d'un
    cabinet OECFM comme le reste des gabarits fiscaux de cette phase) :
    prorata en JOURS calendaires de detention dans l'exercice, plutot qu'un
    prorata en mois (les deux conventions coexistent en pratique
    comptable malgache/francaise ; le decompte en jours est retenu ici car
    il ne demande aucune regle d'arrondi supplementaire "mois entier des
    l'acquisition dans le mois" et reste exact quelle que soit la date
    d'acquisition/cession dans l'exercice) :

        base_amortissable = valeur_acquisition - valeur_residuelle
        annuite_pleine = base_amortissable / duree_utilite_annees
        debut_periode = max(date_acquisition, date_debut_exercice)
        fin_periode = min(date_fin_exercice, date_cession ou date_fin_exercice)
        jours_detenus = (fin_periode - debut_periode).jours + 1
        jours_exercice = (date_fin_exercice - date_debut_exercice).jours + 1
        dotation = annuite_pleine * jours_detenus / jours_exercice

    Si `asset` n'est pas encore acquis ou plus detenu durant `fiscal_year`
    (`debut_periode > fin_periode`), la dotation est 0 plutot qu'une erreur
    (exercice hors de la vie de l'actif — cas legitime, pas une anomalie).

    `opening_accumulated_mga` reprend `closing_accumulated_mga` de la
    derniere annuite calculee sur un exercice anterieur, ou 0 si aucune
    n'existe encore (premier exercice d'amortissement de l'actif).
    `closing_accumulated_mga` est PLAFONNE a `base_amortissable` (on
    n'amortit jamais sous la valeur residuelle) : si l'ouverture + la
    dotation pleine depasserait ce plafond, la dotation de l'exercice est
    elle-meme reduite d'autant (dotation finale = plafond - ouverture),
    documente ici plutot que silencieusement tronque ailleurs.

    Si `post=True`, poste une ecriture reelle (`journal`/`period` requis
    dans ce cas) : debit `dotation_account` (compte 68x — reutilise la meme
    classe que `_CR_NATURE_MAPPING["Dotations aux amortissements et
    provisions"]` de `reports.py`, pour rester coherent avec ACC-CR), credit
    `accumulated_depreciation_account` (compte 28x contre-actif). Si
    `post=False` (par defaut), `move` reste `None` — cf. docstring de
    module : un plan d'amortissement se calcule/relit avant d'etre engage."""
    depreciable_base = asset.acquisition_value_mga - asset.residual_value_mga

    period_start = max(asset.acquisition_date, fiscal_year.date_start)
    period_end = fiscal_year.date_end
    if asset.disposal_date is not None and asset.disposal_date < period_end:
        period_end = asset.disposal_date

    prior = _prior_depreciation(asset, fiscal_year)
    opening_accumulated = prior.closing_accumulated_mga if prior is not None else Decimal(0)

    if period_start > period_end or depreciable_base <= 0:
        annual_dotation = Decimal(0)
    else:
        days_held = (period_end - period_start).days + 1
        days_in_fy = (fiscal_year.date_end - fiscal_year.date_start).days + 1
        full_annual = depreciable_base / Decimal(asset.useful_life_years)
        annual_dotation = (full_annual * Decimal(days_held) / Decimal(days_in_fy)).quantize(
            _QUANT, rounding=ROUND_HALF_UP
        )

    remaining_capacity = depreciable_base - opening_accumulated
    if remaining_capacity < 0:
        remaining_capacity = Decimal(0)
    if annual_dotation > remaining_capacity:
        annual_dotation = remaining_capacity

    closing_accumulated = opening_accumulated + annual_dotation

    move = None
    if post:
        if (
            journal is None
            or period is None
            or dotation_account is None
            or (accumulated_depreciation_account is None)
        ):
            raise ValidationError(
                _(
                    "journal, period, dotation_account et "
                    "accumulated_depreciation_account sont requis pour poster "
                    "la dotation (post=True)."
                )
            )
        draft = create_draft_move(
            tenant=asset.tenant,
            journal=journal,
            period=period,
            date=fiscal_year.date_end,
            narration=_("Dotation aux amortissements — %(asset)s — %(fy)s")
            % {"asset": asset.label, "fy": fiscal_year.code},
        )
        add_line(
            draft,
            account=dotation_account,
            label=_("Dotation amortissement %(asset)s") % {"asset": asset.label},
            debit=annual_dotation,
        )
        add_line(
            draft,
            account=accumulated_depreciation_account,
            label=_("Amortissement cumule %(asset)s") % {"asset": asset.label},
            credit=annual_dotation,
        )
        move = post_move(draft)

    return AccAssetDepreciation.objects.create(
        tenant=asset.tenant,
        asset=asset,
        fiscal_year=fiscal_year,
        opening_accumulated_mga=opening_accumulated,
        annual_dotation_mga=annual_dotation,
        closing_accumulated_mga=closing_accumulated,
        move=move,
    )


def record_provision_movement(
    *,
    tenant: Tenant,
    nature: str,
    account: AccAccount,
    fiscal_year: AccFiscalYear,
    opening_amount_mga: Decimal = Decimal(0),
    dotation_mga: Decimal = Decimal(0),
    reprise_mga: Decimal = Decimal(0),
) -> AccProvision:
    """Enregistre le mouvement (dotation/reprise) d'une provision pour un
    exercice donne — source de l'annexe "Etat des provisions" (§1.11 du
    document annexe). `closing_amount_mga` est PLAFONNE a 0 (une provision
    ne peut pas devenir negative ; une reprise excedant le solde disponible
    est une anomalie de saisie a corriger en amont, pas modelisee ici comme
    une erreur bloquante — le montant est simplement clampe, documente ici).

    Ne poste aucune ecriture reelle en V1 (cf. docstring de module) : la
    comptabilisation de la dotation/reprise reste une operation de cloture
    ordinaire, deja realisable manuellement via
    `create_draft_move`/`add_line`/`post_move`."""
    closing_amount = opening_amount_mga + dotation_mga - reprise_mga
    if closing_amount < 0:
        closing_amount = Decimal(0)

    reference = next_reference(tenant, "PROV", fiscal_year.date_start.year)
    return AccProvision.objects.create(
        tenant=tenant,
        reference=reference,
        nature=nature,
        account=account,
        fiscal_year=fiscal_year,
        opening_amount_mga=opening_amount_mga,
        dotation_mga=dotation_mga,
        reprise_mga=reprise_mga,
        closing_amount_mga=closing_amount,
        move=None,
    )
