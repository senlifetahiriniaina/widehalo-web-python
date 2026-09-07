"""Amorcage du parametre versionne qui porte l'unite de cout de la
messagerie — la reponse a l'hypothese H26.

**Ce que cette migration resout.** Le cahier de la Phase 4 demande de
trancher au sprint 3 si le compteur existant encaisse une bascule vers la
facturation au message, avec pour repli « deux unites de cout coexistent,
avec une date de bascule » au prix d'un sprint supplementaire au bloc H.
Plutot que de parier, l'unite devient une donnee versionnee : la « date de
bascule » n'est alors rien d'autre qu'une ligne de plus avec un
`valid_from`, et le mecanisme demande par le repli existait deja dans ce
depot sans etre employe.

**La valeur semee est celle qui est REELLEMENT en vigueur dans le code
aujourd'hui**, pas celle qu'on souhaiterait : le compteur sommait ligne par
ligne, ce qui est la facturation AU MESSAGE. Semer `conversation` aurait
change en silence le comportement de tous les deploiements existants — soit
exactement le defaut qu'une bascule non datee produit.

**`statut_validation` reste `non_valide`, et c'est voulu** — meme
discipline que les seeds de TVA. Mais pour une raison differente : ce code
n'est PAS inscrit dans `ACTIVE_CALCULATION_PARAMETER_CODES`, parce qu'un
tarif commercial n'est pas un parametre de calcul reglementaire et n'a rien
a faire dans un verrou de mise en production qui attend une validation
OECFM. L'y inscrire bloquerait les livraisons pour l'avis d'un ordre
comptable sur le bareme d'un fournisseur de messagerie.

Bascule, le jour venu : ajouter une ligne
`(code="messagerie.unite_cout", valid_from=<date>, value="message")` et
BORNER celle-ci par `valid_to = <date - 1 jour>`. La contrainte
d'exclusion GiST de la table refuse deux plages qui se chevauchent, ce qui
rend une bascule bâclée impossible plutot qu'invisible.
"""

from __future__ import annotations

import datetime as dt

from django.db import migrations

CODE = "messagerie.unite_cout"
# Meme convention de date d'effet que les seeds fiscaux du depot
# (`accounting/migrations/0030_seed_vat_reference_rate.py`) : 1er janvier de
# l'exercice courant. Anterieure a tout message existant, de sorte qu'aucune
# ligne deja ecrite ne se retrouve sans unite applicable.
EFFECTIVE_DATE = dt.date(2026, 1, 1)
VALUE = "message"
# `legal_reference` est un CharField(255) : le motif long vit dans la
# docstring de cette migration, pas dans la colonne. La première rédaction
# faisait 265 caractères et la base l'a refusée — utilement.
LEGAL_REFERENCE = (
    "Unité de facturation de la messagerie professionnelle. Valeur semée = le "
    "comportement réel du compteur avant ce chantier ; une bascule se fait en "
    "bornant cette ligne et en ajoutant la suivante (hypothèse H26)."
)


def seed_cost_unit(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    RegulatoryParameter.objects.get_or_create(
        tenant=None,
        code=CODE,
        valid_from=EFFECTIVE_DATE,
        defaults={"value": VALUE, "legal_reference": LEGAL_REFERENCE, "valid_to": None},
    )


def remove_cost_unit(apps, schema_editor) -> None:
    RegulatoryParameter = apps.get_model("core", "RegulatoryParameter")
    RegulatoryParameter.objects.filter(tenant=None, code=CODE, valid_from=EFFECTIVE_DATE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0001_initial"),
        ("core", "0034_whatsappmessage_cost_unit"),
    ]

    operations = [migrations.RunPython(seed_cost_unit, remove_cost_unit)]
