"""Construction du « socle de simulation » (cahier §13.6) —
`services.baseline.build_baseline` agrège les données réelles du tenant
(compte de résultat, taux de TVA de référence, position de trésorerie,
échéancier ouvert) en un instantané compact persisté (`SimBaseline`),
consommé ensuite par `services.engine.compute_indicators` sans nouvel
accès base à chaque manipulation de levier (SIM-1/SIM-2).

Traitement SYNCHRONE ici (la construction agrège quelques dizaines de
lignes de compte de résultat + au plus `MAX_OPEN_ITEMS` échéances
ouvertes — coût comparable à un rapport déjà servi en synchrone ailleurs
du dépôt, ex. `apps.accounting.services.reports.treasury_forecast`).
Le cahier (§5.2) liste pourtant explicitement « construction du socle de
simulation » parmi les quatre traitements asynchrones de la Phase 1 — le
point d'appel HTTP (`apps.simulation.views.baseline_refresh`) fait donc
passer cet appel par `apps.core.tasks.enqueue` plutôt que cette fonction
elle-même, qui reste synchrone et directement testable."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from apps.accounting.services.public import (
    get_income_statement_summary,
    get_open_settlement_items,
    get_treasury_forecast_summary,
)
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.regulatory import get_parameter_with_version
from apps.sales.services.public import get_revenue_summary
from apps.simulation.models import SimBaseline

MAX_OPEN_ITEMS = 500
TVA_REGULATORY_CODE = "tva.taux_normal"

_ZERO = Decimal(0)
_STATEMENT_LABELS = {
    "ca_ref": "Chiffre d'affaires",
    "achats_consommes_ref": "Achats consommes",
    "production_stockee_ref": "Production stockee",
    "production_immobilisee_ref": "Production immobilisee",
    "subvention_exploitation_ref": "Subvention d'exploitation",
    "charges_personnel_ref": "Charges de personnel",
    "impots_taxes_ref": "Impots, taxes et versements assimiles",
    "autres_produits_operationnels_ref": "Autres produits operationnels",
    "dotations_ref": "Dotations aux amortissements et provisions",
    "produits_financiers_ref": "Produits financiers",
    "charges_financieres_ref": "Charges financieres",
    "impot_resultats_ref": "Impot sur les resultats",
    "ebe_ref": "EXCEDENT BRUT D'EXPLOITATION",
    "resultat_net_ref": "RESULTAT NET DE L'EXERCICE",
}


def _poste(rows: list[dict[str, Any]], label: str) -> Decimal:
    for row in rows:
        if row["label"] == label:
            amount = row["amount"]
            return amount if isinstance(amount, Decimal) else Decimal(str(amount))
    return _ZERO


def build_baseline(
    tenant: Tenant, *, as_of_date: dt.date | None = None, user: User | None = None
) -> SimBaseline:
    """Reconstruit un `SimBaseline` à partir des données réelles du tenant.
    Ne modifie/ne réutilise jamais un `SimBaseline` existant — chaque appel
    crée un NOUVEAU socle (cf. docstring de `apps.simulation.models.
    SimBaseline` : les scénarios déjà créés référencent le socle qui
    existait à leur création, jamais celui-ci)."""
    as_of = as_of_date or dt.date.today()
    period_start = as_of - dt.timedelta(days=365)

    statement_rows = get_income_statement_summary(tenant, as_of_date=as_of)
    degraded = statement_rows is None
    if degraded:
        # Aucun exercice fiscal ne couvre `as_of_date` (tenant tout juste
        # créé, ou exercice non paramétré) : socle DÉGRADÉ, limité au
        # chiffre d'affaires de `sales` seul — jamais une exception qui
        # empêcherait tout usage du module, jamais une valeur inventée
        # pour les postes de charges (laissés à 0, `degraded=True` permet
        # à l'écran de le signaler explicitement plutôt que de laisser
        # croire à un tenant sans aucune charge).
        ca_ref = get_revenue_summary(date_from=period_start, date_to=as_of)
        raw: dict[str, Decimal] = dict.fromkeys(_STATEMENT_LABELS, _ZERO)
        raw["ca_ref"] = ca_ref
        raw["resultat_net_ref"] = ca_ref
        raw["ebe_ref"] = ca_ref
    else:
        # `degraded = statement_rows is None` ci-dessus garantit deja cette
        # condition — assert de narrowing mypy uniquement, jamais une regle
        # metier.
        assert statement_rows is not None
        raw = {key: _poste(statement_rows, label) for key, label in _STATEMENT_LABELS.items()}

    # L17 — un tenant NON ASSUJETTI n'a pas besoin d'un taux de TVA pour
    # construire un socle, et lui en exiger un l'empechait purement et
    # simplement de simuler. La garde ci-dessous contredisait frontalement
    # `accounting.services.vat_reference.resolve_reference_vat_rate`, qui
    # pose depuis L3 qu'« un tenant peut legitimement n'avoir aucun
    # referentiel de TVA (regime synthetique) ». Deux modules affirmaient
    # l'inverse l'un de l'autre ; c'est celui qui LEVE qui avait tort.
    #
    # Le taux reste EXIGE d'un tenant assujetti : pour lui, l'absence de
    # parametre est bien un gap de configuration, et le socle serait faux
    # sans lui.
    from apps.accounting.services.public import is_vat_liable

    tva_version = None
    if is_vat_liable(tenant):
        try:
            tva_taux_raw, tva_version = get_parameter_with_version(
                TVA_REGULATORY_CODE, as_of, tenant
            )
        except RegulatoryParameter.DoesNotExist as exc:
            raise ValidationError(
                f"Aucun paramètre réglementaire '{TVA_REGULATORY_CODE}' valide au {as_of} — "
                "impossible de construire le socle de simulation sans taux de TVA de référence."
            ) from exc
        tva_taux_ref = Decimal(str(tva_taux_raw))
    else:
        # Zero, et non « pas de valeur » : le moteur multiplie ce taux sans
        # conditionnelle, et un `None` y produirait un TypeError a chaque
        # simulation. Un taux nul donne une TVA nette projetee nulle, ce qui
        # est exactement la realite d'un tenant non assujetti.
        tva_taux_ref = Decimal(0)

    treasury_summary = get_treasury_forecast_summary(tenant, as_of_date=as_of, horizon_days=91)
    starting_cash_mga = treasury_summary["starting_cash_mga"]

    raw_items = get_open_settlement_items(tenant, as_of_date=as_of, horizon_days=91)
    included_items = raw_items[:MAX_OPEN_ITEMS]

    data: dict[str, Any] = {key: str(value) for key, value in raw.items()}
    data["tva_taux_ref"] = str(tva_taux_ref)
    data["starting_cash_mga"] = str(starting_cash_mga)
    data["as_of_date"] = as_of.isoformat()
    data["degraded"] = degraded
    data["open_items"] = [
        {
            "kind": item["kind"],
            "due_date": item["due_date"].isoformat(),
            "amount_mga": str(item["amount_mga"]),
        }
        for item in included_items
    ]

    # FOR-10 (L9) : « la prevision PUBLIEE est disponible comme scenario de
    # reference dans la simulation financiere, AVEC SA VERSION ET SA DATE ».
    #
    # Le patron existait deja — dans un AUTRE module :
    # `strategy.services.budget.create_budget_from_forecast_publication`
    # importe la meme facade en import local et conserve version et date
    # dans `source_reference`. C'est litteralement ce que FOR-10 demande,
    # applique a `strategy` et jamais a `simulation` : `baseline.py`
    # n'avait aucune reference a `apps.forecast`. La tresorerie injectee
    # ci-dessus est la projection COMPTABLE a 91 jours, pas une prevision.
    #
    # Import local : `simulation` ne declare pas `forecast` au niveau
    # module, meme discipline que `strategy`.
    from apps.forecast.services.public import get_latest_published_forecast

    publication = get_latest_published_forecast(tenant)
    if publication is not None:
        # La VERSION et la DATE sont dans le socle, pas seulement les
        # chiffres : un scenario rejoue six mois plus tard doit pouvoir
        # dire sur quelle prevision il s'appuyait, et une prevision
        # republiee depuis ne doit pas se substituer silencieusement a
        # celle qui a servi.
        data["forecast_publication"] = {
            "version": publication["version"],
            "published_at": publication["published_at"].isoformat(),
            "period_start": publication["period_start"].isoformat(),
            "period_end": publication["period_end"].isoformat(),
            "entries": [
                {
                    "dimension_type": entry["dimension_type"],
                    "dimension_value": entry["dimension_value"],
                    "period": str(entry["period"]),
                    "value": str(entry["value"]),
                }
                for entry in publication["snapshot"]
            ],
        }

    return SimBaseline.objects.create(
        tenant=tenant,
        period_start=period_start,
        period_end=as_of,
        as_of_date=as_of,
        # Dictionnaire VIDE quand aucun parametre reglementaire n'est entre
        # dans ce socle (tenant non assujetti), plutot que `{code: None}` :
        # « aucun parametre utilise » et « parametre utilise, version
        # inconnue » ne disent pas la meme chose a qui relira ce socle.
        regulatory_param_version=(
            {TVA_REGULATORY_CODE: tva_version} if tva_version is not None else {}
        ),
        data=data,
        open_items_total_count=len(raw_items),
        open_items_included_count=len(included_items),
        created_by=user,
    )


def refresh_baseline(
    tenant: Tenant, *, as_of_date: dt.date | None = None, user: User | None = None
) -> str:
    """Enfile la reconstruction du socle via `apps.core.tasks.enqueue` —
    cahier §5.2 : « construction du socle de simulation » est explicitement
    listée parmi les quatre traitements asynchrones de la Phase 1. Renvoie
    l'identifiant de tâche Django-Q2 — exécutée en SYNCHRONE dans les
    tests (`Q_CLUSTER["sync"] = True`, cf. `apps.core.tests.test_tasks_
    enqueue`), ce qui permet de tester ce chemin sans mock ni sleep."""
    from apps.core.tasks import enqueue

    return enqueue(
        build_baseline,
        tenant,
        as_of_date=as_of_date,
        user=user,
        task_name=f"simulation-baseline-refresh-{tenant.id}",
    )


def deserialize_baseline_data(baseline: SimBaseline) -> dict[str, Any]:
    """Inverse de la sérialisation faite par `build_baseline` — reconvertit
    `SimBaseline.data` (chaînes JSON, cf. discipline documentée dans
    `apps.core.services.audit._json_safe`/`apps.payroll.services.payslip`)
    en `Decimal`/`date` natifs, seul format consommé par `services.engine.
    compute_indicators`."""
    data = baseline.data
    result: dict[str, Any] = {
        key: Decimal(str(value))
        for key, value in data.items()
        if key not in ("open_items", "as_of_date", "degraded")
    }
    result["as_of_date"] = dt.date.fromisoformat(data["as_of_date"])
    result["open_items"] = [
        {
            "kind": item["kind"],
            "due_date": dt.date.fromisoformat(item["due_date"]),
            "amount_mga": Decimal(item["amount_mga"]),
        }
        for item in data.get("open_items", [])
    ]
    return result
