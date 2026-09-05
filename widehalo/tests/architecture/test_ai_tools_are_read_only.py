"""Garde-fou bloquant (IA-1) : « Le copilote ne dispose que d'outils de
LECTURE ; aucune action d'ecriture n'est atteignable depuis le LLM. »

L'invariant etait respecte avant cette garde — les huit tools du registre
sont tous des rapports agreges — mais **rien de mecanique ne le disait**. La
distinction lecture/ecriture n'etait materialisee nulle part : ni champ, ni
convention verifiee, seulement l'intention de celui qui avait ecrit les
adaptateurs. Rendre l'invariant opposable demandait donc de modifier le
registre, pas seulement d'ajouter un test.

Deviner plutot que declarer n'aurait pas marche : une analyse AST du corps
de chaque fonction de tool ne conclut rien, chacune deleguant a un import
local qu'il faudrait suivre. `read_only` est donc un parametre OBLIGATOIRE
de `register_data_query_tool`, sans valeur par defaut — un defaut permissif
laisserait passer un futur tool d'ecriture par simple oubli.

Deux assertions, pas une : le drapeau declare, et la permission exigee. Un
`required_permission` en `<app>.view_<modele>` est une seconde preuve,
independante du declarant, que le tool est bien du cote lecture du RBAC —
la passerelle filtrant le catalogue sur cette permission AVANT de l'offrir
au LLM (`apps.ai.services.data_query_gateway.ask`), un tool d'ecriture y
serait offert avec une permission `add_`/`change_`.

**Limite assumee** : la garde verifie ce qui est declare et ce qui est
exige, pas ce que la fonction fait reellement. Un adaptateur qui declarerait
`read_only=True` en appelant un service d'ecriture passerait — c'est la
regle de revue du registre, deja ecrite dans sa docstring, qui couvre ce
cas. Ce que la garde rend impossible, c'est l'oubli silencieux.
"""

from __future__ import annotations

import re

_VIEW_PERMISSION = re.compile(r"^[a-z_]+\.view_[a-z0-9_]+$")


def _tools() -> list:
    from apps.core.services.data_query_tool_registry import list_data_query_tools

    return list_data_query_tools()


def test_the_registry_is_populated() -> None:
    """Sans cette assertion, toutes les autres passeraient sur zero tool —
    une garde qui ne regarde rien est une garde qui ne garde rien."""
    assert _tools(), "Aucun tool enregistre : les `ready()` des modules n'ont pas tourne."


def test_every_tool_declares_itself_read_only() -> None:
    writers = [tool.code for tool in _tools() if not tool.read_only]
    assert not writers, (
        "Tool(s) du copilote declare(s) en ecriture, contraire au cahier IA-1 :\n"
        + "\n".join(f"  - {code}" for code in sorted(writers))
    )


def test_every_tool_requires_a_view_permission() -> None:
    offenders = [
        f"{tool.code} → {tool.required_permission}"
        for tool in _tools()
        if not _VIEW_PERMISSION.match(tool.required_permission)
    ]
    assert not offenders, (
        "Tool(s) exigeant une permission qui n'est pas une permission de "
        "lecture `<app>.view_<modele>` :\n" + "\n".join(f"  - {line}" for line in sorted(offenders))
    )


def test_the_registry_refuses_a_write_tool() -> None:
    """Auto-test du detecteur sur un tool d'ecriture factice : sans quoi le
    garde-fou serait un theatre de securite (meme discipline que
    `test_module_boundaries.py::test_forbidden_import_is_detected`).

    Le refus est porte par le registre lui-meme et non par ce test : un tool
    d'ecriture ne doit pas seulement faire echouer la CI, il ne doit jamais
    entrer dans le catalogue offert au LLM."""
    import pytest
    from apps.core.services.data_query_tool_registry import (
        get_data_query_tool,
        register_data_query_tool,
    )

    with pytest.raises(ValueError):
        register_data_query_tool(
            "test.tool_decriture_factice",
            module="test",
            label="Tool d'ecriture factice",
            description="Ne doit jamais etre enregistre.",
            parameters_schema={},
            required_permission="test.add_something",
            read_only=False,
            function=lambda tenant: [],
        )
    assert get_data_query_tool("test.tool_decriture_factice") is None


def test_the_view_permission_detector_catches_a_write_permission() -> None:
    assert not _VIEW_PERMISSION.match("sales.add_salesorder")
    assert not _VIEW_PERMISSION.match("sales.change_salesorder")
    assert _VIEW_PERMISSION.match("sales.view_salesorder")
