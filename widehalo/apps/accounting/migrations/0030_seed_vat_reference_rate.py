"""L3 — sème `tva.taux_normal`, le seul taux légal du produit que rien ne
créait.

**Le défaut fermé ici.** Ce code de paramètre était référencé à quatre
endroits du dépôt — `apps.simulation.services.baseline.TVA_REGULATORY_CODE`,
la docstring de `core.services.regulatory.get_parameter_with_version`, celle
de `accounting.services.public.get_default_sale_tax`, et le commentaire de
`SimBaseline.regulatory_param_version` — et **semé nulle part** : ni
migration, ni commande, ni service. Vérifié de bout en bout sur une base de
démonstration entièrement amorcée : `build_baseline` levait

    Aucun paramètre réglementaire 'tva.taux_normal' valide au ... —
    impossible de construire le socle de simulation sans taux de TVA de
    référence.

Le module Simulation ne pouvait donc construire aucun socle, sur aucune
instance. Le code était juste ; rien ne l'amorçait — même patron que le
calendrier férié (`load_mg_holidays`, fermé en L2-3).

**Valeur globale (`tenant=None`)** et non par tenant : le taux normal de TVA
est une donnée de LOI, pas de société. Un tenant qui aurait besoin d'un taux
différent peut toujours créer sa propre ligne, qui prévaudra
(`services/regulatory.py::get_parameter`).

**`statut_validation` reste `non_valide`**, par défaut du modèle et à
dessein : le cahier (§4) pose que « aucune hypothèse réglementaire ne peut
être levée par défaut au motif que le développement doit avancer ». Semer ce
paramètre déjà validé OECFM contournerait le verrou que L3 vient précisément
d'étendre à ce code. Il doit être validé dans l'admin avant mise en
production, comme les dix paramètres de paie.
"""

from __future__ import annotations

import datetime as dt

from django.db import migrations

CODE = "tva.taux_normal"
# Date d'effet retenue : même convention que le jeu de paie
# (`apps/payroll/services/seed.py::DEFAULT_EFFECTIVE_DATE`), 1er janvier de
# l'exercice fiscal courant du dépôt.
EFFECTIVE_DATE = dt.date(2026, 1, 1)
RATE = "20.00"
LEGAL_REFERENCE = "Code général des impôts malgache — taux normal de TVA (à confirmer OECFM)"


def seed_vat_reference_rate(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    RegulatoryParameter.objects.get_or_create(
        tenant=None,
        code=CODE,
        valid_from=EFFECTIVE_DATE,
        defaults={
            # **Scalaire nu, et non `{"rate": ...}`** — contrairement aux dix
            # paramètres de paie, qui emploient tous une forme de dictionnaire
            # (`{"amount": ...}`, `{"employer": ..., "employee": ...}`).
            #
            # Le contrat scalaire préexiste à ce lot et n'est pas le mien :
            # `apps.simulation.services.baseline` fait
            # `Decimal(str(tva_taux_raw))` sur la valeur brute depuis la
            # Phase 1, et ses propres tests sèment `value=20`. Semer un
            # dictionnaire aurait fait échouer le seul consommateur existant
            # sur un `decimal.ConversionSyntax` — vérifié, c'est exactement ce
            # qui s'est produit au premier essai.
            #
            # `resolve_reference_vat_rate` accepte malgré tout les deux formes,
            # pour ne pas casser un jeu de données déjà saisi à la main.
            "value": RATE,
            "legal_reference": LEGAL_REFERENCE,
            "valid_to": None,
        },
    )


def remove_vat_reference_rate(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    RegulatoryParameter.objects.filter(
        tenant=None, code=CODE, valid_from=EFFECTIVE_DATE
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0029_seed_syscohada_demo"),
        ("core", "0030_hash_email_change_token"),
    ]

    operations = [
        migrations.RunPython(seed_vat_reference_rate, remove_vat_reference_rate),
    ]
