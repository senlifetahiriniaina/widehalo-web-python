"""D-2 — les libelles semes du CRM, accentues dans les societes existantes.

Corriger `services/pipelines.py` ne suffit pas : ces textes sont des
DONNEES, ecrites en base a l'initialisation d'une societe. Une societe
creee avant ce lot garderait « Rendez-vous planifie » indefiniment, sur les
trois ecrans qui l'affichent.

**La correction ne porte que sur le texte EXACT d'origine.** Un nom qu'un
exploitant a renomme lui-meme ne correspond plus, et n'est pas touche : une
migration de donnees ne decide jamais a la place de l'utilisateur.
"""

from __future__ import annotations

from django.db import migrations

CORRECTIONS_ETAPES = {
    "Rendez-vous planifie": "Rendez-vous planifié",
    "Qualifie pour achat": "Qualifié pour achat",
    "Presentation planifiee": "Présentation planifiée",
    "Decideur convaincu": "Décideur convaincu",
    "Contrat envoye": "Contrat envoyé",
    "Gagne": "Gagné",
}
CORRECTIONS_PIPELINES = {
    "Pipeline commercial par defaut": "Pipeline commercial par défaut",
}


def _appliquer(apps, corrections, modele, champ="name"):
    Modele = apps.get_model("crm", modele)
    total = 0
    for ancien, nouveau in corrections.items():
        total += Modele.objects.filter(**{champ: ancien}).update(**{champ: nouveau})
    return total


def accentuer(apps, schema_editor):
    _appliquer(apps, CORRECTIONS_ETAPES, "CrmStage")
    _appliquer(apps, CORRECTIONS_PIPELINES, "CrmPipeline")


def desaccentuer(apps, schema_editor):
    """Reversible : une migration de donnees qui ne sait pas revenir bloque
    tout retour arriere du schema."""
    _appliquer(apps, {v: k for k, v in CORRECTIONS_ETAPES.items()}, "CrmStage")
    _appliquer(apps, {v: k for k, v in CORRECTIONS_PIPELINES.items()}, "CrmPipeline")


class Migration(migrations.Migration):
    dependencies = [("crm", "0003_crmpipeline_stagnant_after_days")]
    operations = [migrations.RunPython(accentuer, desaccentuer)]
