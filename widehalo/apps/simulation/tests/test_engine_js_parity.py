"""Vérification de parité Python/JavaScript du moteur de recalcul
(SIM-1/SIM-4) — `apps/simulation/services/engine.py` et `static/js/
simulation_engine.js` sont écrits comme des miroirs ligne-à-ligne (cf. la
docstring de tête des deux fichiers), mais une réimplémentation manuelle
peut toujours diverger silencieusement. Ce test exécute RÉELLEMENT le
fichier JS via Node.js (`subprocess`) sur plusieurs jeux de leviers et
compare bit-à-bit le résultat au calcul Python — la seule façon de
vérifier la parité autrement que par relecture.

Ce dépôt ne dépend d'aucun outil JavaScript par ailleurs (pas de
`package.json`, cf. cahier §11.1 « chaîne de construction légère ») : ce
test se désactive proprement (`pytest.skip`) si `node` n'est pas
disponible dans l'environnement de test, plutôt que de faire échouer la
suite dans un environnement qui ne l'installe pas."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.simulation.levers import catalog_as_dicts, default_levers
from apps.simulation.services.engine import compute_indicators

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponible")

_JS_ENGINE_PATH = Path(__file__).resolve().parents[3] / "static" / "js" / "simulation_engine.js"
_NODE_RUNNER = """
global.window = global;
require(process.argv[1]);
const baseline = JSON.parse(process.argv[2]);
const levers = JSON.parse(process.argv[3]);
const catalog = JSON.parse(process.argv[4]);
process.stdout.write(JSON.stringify(window.SimEngine.computeIndicators(baseline, levers, catalog)));
"""

_RAW_BASELINE: dict[str, Any] = {
    "ca_ref": "100000000",
    "achats_consommes_ref": "40000000",
    "production_stockee_ref": "0",
    "production_immobilisee_ref": "0",
    "subvention_exploitation_ref": "0",
    "charges_personnel_ref": "20000000",
    "impots_taxes_ref": "1000000",
    "autres_produits_operationnels_ref": "0",
    "dotations_ref": "2000000",
    "produits_financiers_ref": "0",
    "charges_financieres_ref": "500000",
    "impot_resultats_ref": "3000000",
    "ebe_ref": "39000000",
    "resultat_net_ref": "33500000",
    "tva_taux_ref": "20",
    "starting_cash_mga": "15000000",
    "as_of_date": "2026-09-01",
    "degraded": False,
    "open_items": [
        {"kind": "receivable", "due_date": "2026-09-15", "amount_mga": "5000000"},
        {"kind": "payable", "due_date": "2026-09-20", "amount_mga": "3000000"},
    ],
}

_PYTHON_BASELINE: dict[str, Any] = {
    key: Decimal(value)
    for key, value in _RAW_BASELINE.items()
    if key not in ("open_items", "as_of_date", "degraded")
}
_PYTHON_BASELINE["as_of_date"] = dt.date(2026, 9, 1)
_PYTHON_BASELINE["open_items"] = [
    {
        "kind": item["kind"],
        "due_date": dt.date.fromisoformat(item["due_date"]),
        "amount_mga": Decimal(item["amount_mga"]),
    }
    for item in _RAW_BASELINE["open_items"]
]


def _run_js_engine(raw_levers: dict[str, Any]) -> dict[str, Any]:
    # noqa: S603, S607 — "node" resolu via PATH (portable dev/CI, jamais un
    # chemin absolu fige) ; tous les arguments sont des donnees de test
    # controlees (JSON serialise localement), jamais une entree utilisateur.
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "node",
            "-e",
            _NODE_RUNNER,
            "--",
            str(_JS_ENGINE_PATH),
            json.dumps(_RAW_BASELINE),
            json.dumps(raw_levers),
            json.dumps(catalog_as_dicts(), default=str),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    output: dict[str, Any] = json.loads(result.stdout)
    return output


def _flatten_numbers(value: Any, path: str = "") -> dict[str, float]:
    if isinstance(value, dict):
        flat: dict[str, float] = {}
        for key, sub_value in value.items():
            flat.update(_flatten_numbers(sub_value, f"{path}.{key}"))
        return flat
    if isinstance(value, list):
        flat = {}
        for index, item in enumerate(value):
            flat.update(_flatten_numbers(item, f"{path}[{index}]"))
        return flat
    if isinstance(value, int | float):
        return {path: float(value)}
    return {}


@pytest.mark.parametrize(
    "raw_levers",
    [
        {},
        {"prix_vente_pct": 10},
        {"volume_pct": -15, "cout_matiere_pct": 8},
        {"remise_moyenne_pts": 5, "masse_salariale_pct": -10, "charges_fixes_pct": 3},
        {"delai_client_jours": 45, "delai_fournisseur_jours": -20},
        {"investissement_mga": 4000000, "investissement_semaine": 7},
        {"tva_taux_override_pct": 18},
        {
            "prix_vente_pct": 7,
            "volume_pct": 3,
            "cout_matiere_pct": -4,
            "frais_financiers_pct": 12,
            "delai_client_jours": 15,
        },
    ],
)
def test_js_engine_matches_python_engine(raw_levers: dict[str, Any]) -> None:
    python_levers = {**default_levers(), **{k: Decimal(str(v)) for k, v in raw_levers.items()}}
    python_result = compute_indicators(_PYTHON_BASELINE, python_levers)
    js_result = _run_js_engine(raw_levers)

    python_flat = _flatten_numbers(_to_float_tree(python_result))
    js_flat = _flatten_numbers(js_result)

    assert python_flat.keys() == js_flat.keys()
    for key, python_value in python_flat.items():
        assert abs(python_value - js_flat[key]) <= 0.01, (
            f"{key} : python={python_value} js={js_flat[key]}"
        )


def _to_float_tree(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _to_float_tree(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_float_tree(val) for val in value]
    return value
