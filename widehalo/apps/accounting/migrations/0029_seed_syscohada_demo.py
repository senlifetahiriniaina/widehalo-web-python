"""D10-5/D10-6 — referentiel SYSCOHADA de DEMONSTRATION.

Ce referentiel n'existe que pour une raison : prouver, par un test qui cree
un tenant d'un autre pays, que la structure des etats financiers et le plan
de comptes ne sont plus ecrits en Python. C'est la preuve que le critere
ACC-2 demande reellement.

**Ce n'est pas un plan SYSCOHADA reel.** L'ADR
`docs/planning/2026-09-adr-referentiel-comptable.md` le dit explicitement :
« Le jeu SYSCOHADA livre est un jeu de demonstration minimal, dont la seule
fonction est de prouver par un test qu'aucune structure n'est codee en dur.
Il porte la meme reserve que le PCG 2005 deja en place : non valide par un
expert-comptable, a ne jamais presenter comme une nomenclature faisant
autorite. » Ouvrir un tenant OHADA reel suppose un chantier de localisation
distinct, avec un expert-comptable de la zone.

Rappel du cahier §12.2, qui fait de la distinction un invariant produit :
« Madagascar n'est pas membre de l'OHADA. […] Ce sont deux referentiels
distincts : plan de comptes, etats financiers et logiques de retraitement
different. Toute confusion entre les deux produit une comptabilite non
conforme. »
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.db import migrations

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

DEMO_RESERVE = (
    "JEU DE DEMONSTRATION — ce referentiel n'est PAS le SYSCOHADA revise officiel. "
    "Il est livre pour prouver que le plan de comptes et la structure des etats "
    "financiers sont des donnees et non du code. Aucun de ses comptes, aucune de ses "
    "lignes d'etat financier n'a ete valide par un expert-comptable de la zone OHADA. "
    "Ne jamais l'utiliser en production."
)


def seed_demo(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    AccChartOfAccounts = apps.get_model("accounting", "AccChartOfAccounts")
    CountryDefaultsProfile = apps.get_model("core", "CountryDefaultsProfile")

    structure = json.loads(
        (FIXTURES / "statement_structure_syscohada_demo.json").read_text(encoding="utf-8")
    )
    framework, _ = AccFramework.objects.update_or_create(
        code="SYSCOHADA_REVISE",
        defaults={
            "name": "SYSCOHADA revise — jeu de DEMONSTRATION (non valide)",
            "default_country_code": "CI",
            "norm_version": "demonstration",
            "is_active": True,
            "validation_reserve": DEMO_RESERVE,
            # Le SYSCOHADA revise compte une classe de plus que le PCG 2005
            # pour les operations hors activites ordinaires — c'est
            # precisement le genre d'ecart que l'abstraction doit absorber.
            "account_classes": {
                "1": "Comptes de ressources durables",
                "2": "Comptes d'actif immobilise",
                "3": "Comptes de stocks",
                "4": "Comptes de tiers",
                "5": "Comptes de tresorerie",
                "6": "Comptes de charges des activites ordinaires",
                "7": "Comptes de produits des activites ordinaires",
                "8": "Comptes des autres charges et produits HAO",
            },
            "class_classification": {
                "1": "ressources_durables",
                "2": "immobilisations",
                "3": "stocks",
                "4": "tiers",
                "5": "tresorerie",
                "6": "charges",
                "7": "produits",
                "8": "hao",
            },
            "financial_income_prefixes": ["77"],
            "suspense_account_code": "471",
            "suspense_account_class": 4,
            "bank_account_prefix": "521",
            "cash_account_prefix": "571",
            "expense_class": 6,
            "income_class": 7,
            "investing_class": 2,
            "statement_structure": structure,
        },
    )

    AccChartOfAccounts.objects.update_or_create(
        framework=framework,
        country_code="CI",
        defaults={
            "name": "Plan de comptes SYSCOHADA — jeu de demonstration",
            "is_default_for_country": True,
            "fixture_name": "syscohada_revise_demo.json",
        },
    )

    # Sans profil pays, `chart_for_country("CI")` ne resout rien et un tenant
    # ivoirien ne recevrait aucun plan : c'est exactement le chemin
    # « tenant -> pays -> referentiel » que D10-5 rend operant.
    CountryDefaultsProfile.objects.update_or_create(
        country_code="CI",
        defaults={
            "base_currency": "XOF",
            "default_language": "fr",
            "timezone": "Africa/Abidjan",
            "chart_of_accounts_code": "SYSCOHADA_REVISE",
        },
    )


def unseed_demo(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    AccChartOfAccounts = apps.get_model("accounting", "AccChartOfAccounts")
    CountryDefaultsProfile = apps.get_model("core", "CountryDefaultsProfile")

    AccChartOfAccounts.objects.filter(framework__code="SYSCOHADA_REVISE").delete()
    AccFramework.objects.filter(code="SYSCOHADA_REVISE").delete()
    CountryDefaultsProfile.objects.filter(country_code="CI").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0028_seed_statement_structure"),
        ("core", "0011_seed_country_defaults_madagascar"),
    ]

    operations = [migrations.RunPython(seed_demo, unseed_demo)]
