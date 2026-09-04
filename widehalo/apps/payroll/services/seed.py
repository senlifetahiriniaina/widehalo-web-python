"""Charge les parametres reglementaires §5.10.3 dans `core.RegulatoryParameter`
(mecanisme Lot 1 etape 10, reutilise tel quel — AUCUN nouveau modele de
parametrage cree pour ce chantier) — meme discipline documentaire que
`apps.accounting.management.commands.load_pcg2005`/`pcg2005_mg.json`.

**RESERVE EXPLICITE DU CDC, reprise ICI VERBATIM (§5.10.3)** : « Ces valeurs
sont indicatives et divergent selon les sources consultees. Elles
constituent un jeu de donnees initial a confirmer, non une verite
juridique. » **Tous les baremes et taux ci-dessous doivent etre valides par
un expert-comptable OECFM avant production** — meme reserve que le PCG 2005
deja appliquee partout dans `accounting`."""

from __future__ import annotations

import datetime as dt

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant

# Date d'effet par defaut retenue pour ce jeu de donnees initial : la LF 2026
# citee pour le bareme IRSA (loi n°2025-021) s'applique a l'exercice fiscal
# 2026 — 1er janvier 2026 retenu par convention pour tous les parametres
# SAUF le SME, dont le decret d'application (n°2026-1352) fixe explicitement
# une date d'effet distincte au 1er mars 2026 (cf. `SME_EFFECTIVE_DATE`).
DEFAULT_EFFECTIVE_DATE = dt.date(2026, 1, 1)
SME_EFFECTIVE_DATE = dt.date(2026, 3, 1)

CODE_IRSA_BRACKETS = "payroll.irsa_brackets"
CODE_IRSA_MINIMUM = "payroll.irsa_minimum"
CODE_IRSA_DEPENDENT_REDUCTION = "payroll.irsa_dependent_reduction"
CODE_CNAPS_RATE = "payroll.cnaps_rate"
CODE_OSTIE_RATE = "payroll.ostie_rate"
# X3 refonte UX (Sprint 8 / L5, cf. docs/planning/2026-refonte-ux-sprints.md
# §5) : FMFP absent du depot avant ce lot (aucun code/seed) — seul le
# taux employeur existe (le CDC ne mentionne aucune part salariale pour le
# FMFP), meme plafond que CNaPS/OSTIE (8×SME).
CODE_FMFP_RATE = "payroll.fmfp_rate"
CODE_SME = "payroll.sme"
CODE_SOCIAL_CEILING_MULTIPLIER = "payroll.social_ceiling_multiplier"
CODE_OVERTIME_EXEMPT_HOURS = "payroll.overtime_exempt_hours"
# Bloc E, E1 (PAY-1) : multiplicateurs par categorie d'heures
# supplementaires — auparavant un dict Python en dur
# (`apps.payroll.services.expr.DEFAULT_OVERTIME_MULTIPLIERS`, retire par
# ce chantier), desormais un `RegulatoryParameter` versionne comme tous
# les autres baremes/taux de ce fichier (§5.10.6, RG-PAY-1). Memes valeurs
# numeriques que l'ancien defaut — aucun changement de comportement pour
# les tenants deja seedes avant ce chantier.
CODE_OVERTIME_MULTIPLIERS = "payroll.overtime_multipliers"


def seed_payroll_regulatory_params(tenant: Tenant, *, effective_date: dt.date | None = None) -> int:
    """Idempotent (par (tenant, code, valid_from) — ne recree pas une plage
    deja presente). Retourne le nombre de parametres effectivement crees."""
    effective_date = effective_date or DEFAULT_EFFECTIVE_DATE
    entries = [
        (
            CODE_IRSA_BRACKETS,
            [
                {"min": "0", "max": "350000", "rate": "0.00"},
                {"min": "350001", "max": "400000", "rate": "0.05"},
                {"min": "400001", "max": "500000", "rate": "0.10"},
                {"min": "500001", "max": "600000", "rate": "0.15"},
                {"min": "600001", "max": "4000000", "rate": "0.20"},
                {"min": "4000001", "max": None, "rate": "0.25"},
            ],
            "LF 2026, loi n°2025-021",
            effective_date,
        ),
        (
            CODE_IRSA_MINIMUM,
            {"amount": "3000"},
            "Art. 01.03.16 CGI",
            effective_date,
        ),
        (
            CODE_IRSA_DEPENDENT_REDUCTION,
            {"amount": "2000"},
            "CGI",
            effective_date,
        ),
        (
            CODE_CNAPS_RATE,
            {"employer": "0.13", "employee": "0.01"},
            "CNaPS",
            effective_date,
        ),
        (
            CODE_OSTIE_RATE,
            {"employer": "0.05", "employee": "0.01"},
            "OSTIE",
            effective_date,
        ),
        (
            CODE_FMFP_RATE,
            {"employer": "0.01", "employee": "0.00"},
            "Fonds Malgache de Formation Professionnelle",
            effective_date,
        ),
        (
            CODE_SME,
            {"amount": "300000"},
            "Decret n°2026-1352",
            SME_EFFECTIVE_DATE,
        ),
        (
            CODE_SOCIAL_CEILING_MULTIPLIER,
            {"multiplier": "8"},
            "CNaPS/OSTIE",
            effective_date,
        ),
        (
            CODE_OVERTIME_EXEMPT_HOURS,
            {"hours": "20"},
            "CGI",
            effective_date,
        ),
        (
            CODE_OVERTIME_MULTIPLIERS,
            {
                "h_sup_30": "1.30",
                "h_sup_50": "1.50",
                "nuit": "1.30",
                "dimanche": "1.40",
                "ferie": "2.00",
            },
            "Code du Travail",
            effective_date,
        ),
    ]
    created = 0
    for code, value, legal_reference, valid_from in entries:
        _obj, was_created = RegulatoryParameter.objects.get_or_create(
            tenant=tenant,
            code=code,
            valid_from=valid_from,
            defaults={"value": value, "legal_reference": legal_reference, "valid_to": None},
        )
        created += int(was_created)
    return created
