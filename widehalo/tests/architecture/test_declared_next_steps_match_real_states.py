"""Garde C-3 : une table d'etats qui ne correspond plus a rien se vide en
silence.

`SalesQuotation` et `LogTrip` n'ont pas de machine a etats : leurs suites
sont declarees a la main, etat par etat, dans
`services/next_steps_registration.py`. Rien ne relie ces cles au champ
qu'elles pretendent decrire. Renommez un etat dans le modele et la table
ne correspond plus : `declared_next_steps` rend une liste vide, l'ecran
cesse de proposer quoi que ce soit, et AUCUN test ne rougit — le bandeau
de C-4 serait simplement vide pour toujours.

Cette garde relie les deux : chaque etat cite doit exister dans les
`choices` du champ, source independante de la table qu'elle surveille
(lecon F60 de T6).
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

#: (modele, champ d'etat, table declaree). Ecrit ici plutot qu'importe
#: d'un module metier : la garde doit tomber si le module cesse de
#: declarer, pas suivre le module dans son silence.
TABLES_DECLAREES = (
    (
        "sales.SalesQuotation",
        "state",
        "apps.sales.services.next_steps_registration",
        "_QUOTATION_STEPS",
    ),
    (
        "logistics.LogTrip",
        "status",
        "apps.logistics.services.next_steps_registration",
        "_TRIP_STEPS",
    ),
)


@pytest.mark.parametrize("label,champ,module,constante", TABLES_DECLAREES)
def test_declared_states_exist_on_the_model(
    label: str, champ: str, module: str, constante: str
) -> None:
    import importlib

    table = getattr(importlib.import_module(module), constante)
    assert table, f"{module}.{constante} est vide : l'ecran ne proposera jamais rien."

    modele = django_apps.get_model(label)
    reels = {valeur for valeur, _libelle in modele._meta.get_field(champ).choices}
    inconnus = sorted(set(table) - reels)
    assert not inconnus, (
        f"{module}.{constante} cite des etats qui n'existent pas sur "
        f"{label}.{champ} : {inconnus}. Etats reels : {sorted(reels)}. Un etat renomme "
        f"vide la table sans qu'aucun test ne rougisse."
    )


@pytest.mark.parametrize("label,champ,module,constante", TABLES_DECLAREES)
def test_every_declared_step_carries_a_readable_label(
    label: str, champ: str, module: str, constante: str
) -> None:
    """Un code de transition n'est pas un libelle.

    `core` ne peut pas deviner que `convert_to_order` se dit « Convertir en
    commande » : c'est au module de l'ecrire, et rien ne l'y oblige sans
    cette garde."""
    import importlib

    table = getattr(importlib.import_module(module), constante)
    muettes = [
        (etat, suite.code)
        for etat, suites in table.items()
        for suite in suites
        if not suite.label or suite.label == suite.code
    ]
    assert not muettes, (
        f"Ces suites de {module}.{constante} n'ont pas de libelle lisible : {muettes}."
    )
