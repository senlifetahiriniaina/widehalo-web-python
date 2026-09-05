"""D10 — amorce le referentiel PCG 2005 et y rattache les comptes existants.

Sort du code applicatif tout ce qui, jusqu'ici, etait une hypothese PCG
figee : les classes de compte (`AccAccount.account_class`,
help_text="Classe PCG, 1 a 7"), le compte d'attente
(`chart_of_accounts.SUSPENSE_ACCOUNT_CODE = "471"` et son `account_class=4`),
les prefixes de resolution des journaux de tresorerie ("512"/"530" de
`_DEFAULT_JOURNALS`), les classes de classification du compte de resultat par
fonction et du flux de tresorerie (`reports.py`), le classement DCOM
(`dcom.py::_CLASSIFICATION_BY_PCG_CLASS`) et les prefixes de produits
financiers (`ircm.py::_FINANCIAL_INCOME_PREFIXES`).

Les valeurs sont reprises **a l'identique** des constantes du code : cette
migration ne corrige aucune donnee, elle les deplace. Le recablage des
consommateurs se fait aux sprints D10-3 et D10-4.

La reserve OECFM, jusqu'ici enfouie dans la docstring de
`services/chart_of_accounts.py`, devient une donnee portee par le
referentiel et affichable a l'ecran.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations

PCG_RESERVE = (
    "Jeu de donnees REPRESENTATIF et SIMPLIFIE (pas exhaustif), non valide par un "
    "expert-comptable membre de l'OECFM. A valider avant toute utilisation en "
    "production (cahier des charges Phase 1, §5.1.6). Les valeurs par defaut de "
    "`is_current` (courant/non courant) et de `functional_destination` portees par la "
    "fixture relevent de la meme reserve."
)


def seed_pcg2005(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    AccChartOfAccounts = apps.get_model("accounting", "AccChartOfAccounts")
    AccAccount = apps.get_model("accounting", "AccAccount")

    framework, _ = AccFramework.objects.update_or_create(
        code="PCG2005",
        defaults={
            "name": "Plan Comptable General 2005 (Madagascar)",
            "default_country_code": "MG",
            # Decret n° 2004-272 du 18 fevrier 2004 (cf. cahier Phase 1 §12.2).
            "norm_version": "2005",
            "is_active": True,
            "validation_reserve": PCG_RESERVE,
            "account_classes": {
                "1": "Comptes de capitaux",
                "2": "Comptes d'immobilisations",
                "3": "Comptes de stocks et en-cours",
                "4": "Comptes de tiers",
                "5": "Comptes financiers",
                "6": "Comptes de charges",
                "7": "Comptes de produits",
            },
            # Repris tel quel de `dcom.py::_CLASSIFICATION_BY_PCG_CLASS` — y
            # compris sa reserve : ce n'est PAS la classification officielle
            # des 9 canevas DGI, c'est un classement de repli.
            "class_classification": {
                "1": "capitaux",
                "2": "immobilisations",
                "3": "stocks",
                "4": "tiers",
                "5": "tresorerie",
                "6": "achats",
                "7": "ventes",
            },
            "financial_income_prefixes": ["76", "77"],
            "suspense_account_code": "471",
            "suspense_account_class": 4,
            "bank_account_prefix": "512",
            "cash_account_prefix": "530",
            "expense_class": 6,
            "income_class": 7,
            "investing_class": 2,
        },
    )

    chart, _ = AccChartOfAccounts.objects.update_or_create(
        framework=framework,
        country_code="MG",
        defaults={
            "name": "Plan de comptes PCG 2005 — Madagascar",
            "is_default_for_country": True,
            "fixture_name": "pcg2005_mg.json",
        },
    )

    # Tous les comptes deja crees le sont necessairement par `load_pcg2005`,
    # `ensure_suspense_account` ou un import utilisateur sur ce meme plan :
    # le depot n'a jamais eu qu'un seul referentiel actif.
    AccAccount.objects.filter(chart__isnull=True).update(chart=chart)


def unseed_pcg2005(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    AccChartOfAccounts = apps.get_model("accounting", "AccChartOfAccounts")
    AccAccount = apps.get_model("accounting", "AccAccount")

    charts = AccChartOfAccounts.objects.filter(framework__code="PCG2005")
    AccAccount.objects.filter(chart__in=charts).update(chart=None)
    charts.delete()
    AccFramework.objects.filter(code="PCG2005").delete()


class Migration(migrations.Migration):
    dependencies = [("accounting", "0025_referentiel_comptable")]

    operations = [migrations.RunPython(seed_pcg2005, unseed_pcg2005)]
