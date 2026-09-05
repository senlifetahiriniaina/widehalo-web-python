"""D10-3 — la structure des etats financiers devient une donnee du referentiel.

Charge dans `AccFramework.statement_structure` la structure du compte de
resultat par nature du PCG 2005 et l'ordre de presentation du bilan, jusqu'ici
ecrits en Python dans `services/reports.py` :
`_CR_NATURE_MAPPING` (12 postes, 61 prefixes de compte, « retranscrite
VERBATIM depuis l'Annexe II du PCG 2005 »), la cascade des neuf soldes
intermediaires I a IX, et `_ASSET_TYPE_ORDER`/`_LIABILITY_TYPE_ORDER`.

Le contenu a ete **extrait du module lui-meme**, pas retranscrit a la main :
cette migration deplace une structure a l'identique, elle n'en corrige aucune
ligne. Sa reserve OECFM est celle du reste du referentiel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.db import migrations

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "statement_structure_pcg2005.json"


def seed_structure(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    structure = json.loads(FIXTURE.read_text(encoding="utf-8"))
    AccFramework.objects.filter(code="PCG2005").update(statement_structure=structure)


def unseed_structure(apps: Any, schema_editor: Any) -> None:
    AccFramework = apps.get_model("accounting", "AccFramework")
    AccFramework.objects.filter(code="PCG2005").update(statement_structure={})


class Migration(migrations.Migration):
    dependencies = [("accounting", "0027_statement_structure")]

    operations = [migrations.RunPython(seed_structure, unseed_structure)]
