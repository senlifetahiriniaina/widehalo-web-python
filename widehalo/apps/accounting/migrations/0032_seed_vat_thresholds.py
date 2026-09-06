"""L17 — seme `tva.seuil_assujettissement` et `tva.taux_export`, les deux
derniers parametres de TVA que le cahier des charges declare et que rien ne
creait.

**Le defaut ferme.** La table d'amorcage de la Phase 1
(`docs/cdc-complet/phase-1-…:751`) liste trois parametres de TVA. L3 avait
seme le premier (`tva.taux_normal`) apres avoir constate qu'il etait
reference a quatre endroits et cree nulle part. Les deux autres n'etaient
meme pas references : recherche exhaustive sur tout le depot,
`seuil_assujettissement` et `taux_export` n'apparaissent dans AUCUN fichier
Python. Le cahier les declare, le produit les ignore.

Conséquence directe, et c'est ce qui rend l'amorcage necessaire plutot que
cosmetique : `Tenant.vat_opted_in` documente sur quinze lignes que l'option
d'assujettissement « n'a de sens que pour un tenant dont le CA reel tombe
dans cette tranche precise », et renvoie a « un futur ecran de configuration
fiscale » pour guider ce choix. Cet ecran arrive avec ce lot — il ne peut
pas afficher un seuil qui n'existe pas.

**Valeurs globales (`tenant=None`)**, comme `tva.taux_normal` : un seuil
d'assujettissement est une donnee de LOI, pas de societe. Un tenant qui
aurait besoin d'une valeur differente peut creer sa propre ligne, qui
prevaudra (`core.services.regulatory.get_parameter`).

**`statut_validation` reste `non_valide`**, par defaut du modele et a
dessein : le cahier pose qu'« aucune hypothese reglementaire ne peut etre
levee par defaut au motif que le developpement doit avancer », et ces deux
valeurs sont marquees « A valider OECFM » dans la table d'amorcage
elle-meme. Elles doivent etre validees dans l'admin avant mise en
production, comme les dix parametres de paie et comme le taux normal.
"""

from __future__ import annotations

import datetime as dt

from django.db import migrations

# Meme convention de date d'effet que `0030_seed_vat_reference_rate` et que
# le jeu de paie : 1er janvier de l'exercice fiscal courant du depot.
EFFECTIVE_DATE = dt.date(2026, 1, 1)

SEEDS = [
    {
        "code": "tva.seuil_assujettissement",
        # **Dictionnaire et non scalaire nu**, contrairement a
        # `tva.taux_normal`. Ce n'est pas une incoherence : le taux normal
        # est scalaire parce que `simulation.services.baseline` le lisait
        # deja ainsi depuis la Phase 1 (contrat preexistant qu'on ne pouvait
        # pas casser). Ici, aucun consommateur n'existe encore, et le
        # parametre porte DEUX bornes indissociables — le seuil
        # d'assujettissement obligatoire et le plancher a partir duquel
        # l'option devient ouverte. Les separer en deux codes laisserait la
        # porte a un jeu de donnees ou l'un est valide et l'autre non.
        "value": {"seuil_mga": "400000000", "plancher_option_mga": "200000000"},
        # `legal_reference` est un CharField(255) : la justification longue
        # vit dans la docstring de ce fichier, pas dans la colonne.
        "legal_reference": (
            "CGI malgache — assujettissement TVA : seuil 400 M Ar de CA annuel HT, "
            "option ouverte entre 200 et 400 M Ar (LF 2026), impot synthetique en deca "
            "de 200 M Ar. A CONFIRMER OECFM/DGI (source non primaire)."
        ),
    },
    {
        "code": "tva.taux_export",
        # Scalaire, comme `tva.taux_normal` : c'est un taux, et la symetrie
        # avec lui compte plus ici que la symetrie avec la ligne ci-dessus.
        "value": "0.00",
        "legal_reference": (
            "Code general des impots malgache — taux de TVA applicable aux exportations. "
            "A CONFIRMER OECFM/DGI."
        ),
    },
]


def seed_vat_thresholds(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    for seed in SEEDS:
        RegulatoryParameter.objects.get_or_create(
            tenant=None,
            code=seed["code"],
            valid_from=EFFECTIVE_DATE,
            defaults={
                "value": seed["value"],
                "legal_reference": seed["legal_reference"],
                "valid_to": None,
            },
        )


def remove_vat_thresholds(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    RegulatoryParameter.objects.filter(
        tenant=None,
        code__in=[seed["code"] for seed in SEEDS],
        valid_from=EFFECTIVE_DATE,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0031_closed_period_write_lock"),
    ]

    operations = [
        migrations.RunPython(seed_vat_thresholds, remove_vat_thresholds),
    ]
