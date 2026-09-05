"""Verrou de mise en production sur les parametres reglementaires — cahier
des charges WideHalo v3, Phase 1, §13.3 (ACC-9) : « Un test d'integration
continue empeche tout deploiement en production si un parametre utilise
par un calcul actif porte le statut NON_VALIDE. La validation par un
expert-comptable membre de l'OECFM n'est donc pas une bonne pratique
documentaire : c'est une condition technique de deploiement. »

Ecart confirme par l'audit
`docs/audit/2026-09-cahier-des-charges-v3-audit.md` (ACC-9, §9) : ce
verrou n'existait pas avant ce module — `RegulatoryParameter` n'avait meme
pas de champ de statut de validation (ajoute par la migration
`core.0028_regulatoryparameter_validation_status`).

Usage reel (pipeline de deploiement, cf. docs/DEPLOYMENT_HETZNER.md) :
`python manage.py check_regulatory_validation` sort en erreur (code 1) et
liste chaque parametre bloquant s'il en existe. Usage test (CI) :
`apps/core/tests/test_regulatory_deployment_gate.py` verifie la logique
elle-meme avec des donnees de test — un vrai test d'integration continue
« sur la production » supposerait d'executer ce verrou contre les donnees
reellement seedees du serveur cible, hors de portee d'un job GitHub
Actions qui ne connait pas cet etat (cf. commentaire de tete du fichier de
test)."""

from __future__ import annotations

import datetime as dt

from django.db.models import Q

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant

# Codes de `core_regulatory_parameter` reellement lus par un calcul actif
# et deja livre (par opposition a un parametre seede par anticipation d'un
# module futur, cf. cahier §12.3 : « Les valeurs relatives a la paie ne
# servent aucun ecran de Phase 1... chargees des maintenant » — mais dans
# CE depot, `payroll` est deja construit et son moteur `compute_payslip`
# lit reellement ces 9 codes via `apps.payroll.services.params.
# resolve_params`, cf. apps/payroll/services/seed.py pour leur definition).
#
# Registre explicite et documente (meme discipline que
# `BUDGET_MAX_*`/`SENSITIVE_FIELDS`/`INTENTIONALLY_OPEN_ENDPOINTS`) plutot
# qu'une detection automatique par introspection de code : un parametre
# entre dans ce registre par decision explicite au moment ou le calcul qui
# le consomme est livre, jamais par accident.
ACTIVE_CALCULATION_PARAMETER_CODES: frozenset[str] = frozenset(
    {
        "payroll.irsa_brackets",
        "payroll.irsa_minimum",
        "payroll.irsa_dependent_reduction",
        "payroll.cnaps_rate",
        "payroll.ostie_rate",
        "payroll.fmfp_rate",
        "payroll.sme",
        "payroll.social_ceiling_multiplier",
        "payroll.overtime_exempt_hours",
        # Bloc E, E1 (PAY-1) : ancien defaut en dur
        # (`apps.payroll.services.expr.DEFAULT_OVERTIME_MULTIPLIERS`) retire,
        # desormais reellement lu par `overtime_total_pay`/
        # `overtime_exempt_pay` via `PayrollParams.overtime_multipliers`.
        "payroll.overtime_multipliers",
        # L3 (D9) — le taux normal de TVA entre enfin dans ce registre.
        #
        # Il etait, jusqu'a ce lot, le SEUL taux legal du produit a echapper
        # au verrou de validation OECFM, alors que les dix parametres de paie
        # ci-dessus y sont soumis depuis la Phase 3. L'ecart etait d'autant
        # moins visible que le code `tva.taux_normal` etait reference a quatre
        # endroits du depot et **seme nulle part** : un registre qui liste un
        # parametre inexistant ne bloque rien, et un parametre qu'aucune
        # migration ne cree ne se signale jamais.
        #
        # Les deux moities sont donc livrees ensemble : la migration
        # `accounting/0030_seed_vat_reference_rate.py` cree le parametre, et
        # cette ligne le place sous le verrou. Consequence assumee et voulue :
        # `check_regulatory_validation` refusera desormais la mise en
        # production tant que ce taux n'aura pas ete valide par un
        # expert-comptable OECFM — exactement comme pour l'IRSA.
        #
        # Lu par `accounting.services.vat_reference.resolve_reference_vat_rate`,
        # a la DATE DU DOCUMENT, et par `simulation.services.baseline` depuis
        # la Phase 1.
        "tva.taux_normal",
    }
)


def _effective_rows(
    code: str, at_date: dt.date, tenant: Tenant | None
) -> list[RegulatoryParameter]:
    """Toutes les lignes effectivement resolvables a `at_date` pour ce
    `code` — la valeur globale (`tenant=None`) ET, si `tenant` est fourni,
    une eventuelle surcharge specifique a ce tenant (les DEUX peuvent
    bloquer le deploiement : une surcharge tenant non validee est tout
    aussi active qu'une valeur globale non validee, cf.
    `services/regulatory.py::get_parameter` qui la fait prevaloir)."""
    base_qs = RegulatoryParameter.objects.filter(code=code, valid_from__lte=at_date).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=at_date)
    )
    rows = list(base_qs.filter(tenant__isnull=True))
    if tenant is not None:
        rows += list(base_qs.filter(tenant=tenant))
    return rows


def unvalidated_active_parameters(
    *, at_date: dt.date | None = None, tenants: list[Tenant] | None = None
) -> list[RegulatoryParameter]:
    """Renvoie chaque `RegulatoryParameter` actuellement effectif (a
    `at_date`, defaut aujourd'hui), pour un code de
    `ACTIVE_CALCULATION_PARAMETER_CODES`, dont `statut_validation` vaut
    encore `STATUS_NON_VALIDE` — sur la valeur globale et, si `tenants` est
    fourni, sur chaque surcharge tenant effective. Liste vide = rien ne
    bloque le deploiement."""
    resolved_at = at_date or dt.date.today()
    blocking: list[RegulatoryParameter] = []
    seen_ids: set[str] = set()

    tenant_list: list[Tenant | None] = [None, *(tenants or [])]
    for code in sorted(ACTIVE_CALCULATION_PARAMETER_CODES):
        for tenant in tenant_list:
            for row in _effective_rows(code, resolved_at, tenant):
                if str(row.id) in seen_ids:
                    continue
                seen_ids.add(str(row.id))
                if row.statut_validation != RegulatoryParameter.STATUS_VALIDE_OECFM:
                    blocking.append(row)
    return blocking
