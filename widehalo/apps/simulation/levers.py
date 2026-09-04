"""Catalogue statique des leviers manipulables de l'atelier de scénarios
(cahier §13.6, tableau « Leviers et indicateurs de la Phase 1 »). Un
catalogue en code plutôt qu'un modèle en base (cf. docstring de tête de
`apps.simulation.models`) : bornes/unités/familles ne sont jamais éditées
par un tenant, seule leur VALEUR par scénario l'est (`SimScenario.levers`).

`services.engine.compute_indicators` est l'UNIQUE consommateur autorisé des
clés définies ici (chaque clé de `LEVER_CATALOG` correspond exactement à un
paramètre lu par le moteur, cf. sa docstring) — toute clé absente de ce
catalogue est silencieusement ignorée par `clamp_levers` plutôt que
transmise telle quelle au moteur, garde-fou explicite contre une clé
inventée par un appelant (UI, API, ou proposition IA, cf. SIM-8)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NamedTuple


class LeverDefinition(NamedTuple):
    code: str
    family: str
    label: str
    unit: str
    min_value: Decimal
    max_value: Decimal
    default: Decimal


LEVER_CATALOG: tuple[LeverDefinition, ...] = (
    # --- Commercial ---
    LeverDefinition(
        "prix_vente_pct", "commercial", "Prix de vente", "%", Decimal(-50), Decimal(100), Decimal(0)
    ),
    LeverDefinition(
        "volume_pct", "commercial", "Volume", "%", Decimal(-90), Decimal(200), Decimal(0)
    ),
    LeverDefinition(
        "remise_moyenne_pts",
        "commercial",
        "Remise moyenne supplémentaire",
        "pts",
        Decimal(0),
        Decimal(50),
        Decimal(0),
    ),
    # --- Achats et production ---
    LeverDefinition(
        "cout_matiere_pct", "achats", "Coût matière", "%", Decimal(-50), Decimal(100), Decimal(0)
    ),
    LeverDefinition(
        "taux_change_pct",
        "achats",
        "Taux de change MGA/EUR/USD/CNY",
        "%",
        Decimal(-50),
        Decimal(100),
        Decimal(0),
    ),
    LeverDefinition(
        "transport_douane_pct",
        "achats",
        "Coût transport et droits à l'import",
        "%",
        Decimal(-50),
        Decimal(100),
        Decimal(0),
    ),
    # --- Structure ---
    LeverDefinition(
        "masse_salariale_pct",
        "structure",
        "Masse salariale",
        "%",
        Decimal(-50),
        Decimal(100),
        Decimal(0),
    ),
    LeverDefinition(
        "charges_fixes_pct",
        "structure",
        "Charges fixes (structure)",
        "%",
        Decimal(-50),
        Decimal(100),
        Decimal(0),
    ),
    LeverDefinition(
        "frais_financiers_pct",
        "structure",
        "Frais financiers",
        "%",
        Decimal(-90),
        Decimal(200),
        Decimal(0),
    ),
    LeverDefinition(
        "investissement_mga",
        "structure",
        "Investissement",
        "MGA",
        Decimal(0),
        Decimal(10_000_000_000),
        Decimal(0),
    ),
    LeverDefinition(
        "investissement_semaine",
        "structure",
        "Semaine de l'investissement",
        "semaine",
        Decimal(0),
        Decimal(12),
        Decimal(0),
    ),
    # --- Trésorerie ---
    LeverDefinition(
        "delai_client_jours",
        "tresorerie",
        "Délai de règlement client",
        "jours",
        Decimal(-90),
        Decimal(180),
        Decimal(0),
    ),
    LeverDefinition(
        "delai_fournisseur_jours",
        "tresorerie",
        "Délai de règlement fournisseur",
        "jours",
        Decimal(-90),
        Decimal(180),
        Decimal(0),
    ),
    # --- Fiscal ---
    # Bornes [-1, 50] et non [0, 50] : -1 est la SENTINELLE « pas de
    # dérogation, taux de référence du socle » (cf. `TVA_OVERRIDE_NONE`
    # ci-dessous) — la borne basse doit l'inclure, sous peine que `clamp_
    # levers` l'écrase silencieusement à 0 à chaque réenregistrement d'un
    # scénario qui n'utilise pas cette dérogation (le client renvoie
    # toujours le jeu complet des leviers courants, sentinelle comprise).
    LeverDefinition(
        "tva_taux_override_pct",
        "fiscal",
        "Taux de TVA (dérogation)",
        "%",
        Decimal(-1),
        Decimal(50),
        Decimal(-1),
    ),
)

_BY_CODE = {lever.code: lever for lever in LEVER_CATALOG}

# Sentinelle : `tva_taux_override_pct = -1` (hors bornes usuelles 0-50)
# signifie « pas de dérogation, utiliser le taux de référence du socle » —
# un taux de TVA négatif n'a pas de sens économique, ce qui en fait une
# sentinelle sûre sans avoir besoin d'un `None` dans un JSONField (les
# valeurs JSON `null` compliqueraient inutilement la comparaison de
# tolérance cliente/serveur de SIM-4).
TVA_OVERRIDE_NONE = Decimal(-1)


def default_levers() -> dict[str, Decimal]:
    return {lever.code: lever.default for lever in LEVER_CATALOG}


def clamp_levers(raw_levers: dict[str, Any]) -> dict[str, Decimal]:
    """Ne renvoie QUE les clés connues de `LEVER_CATALOG`, chacune bornée à
    `[min_value, max_value]` — toute clé inconnue est silencieusement
    écartée (jamais transmise au moteur), toute valeur non numérique lève
    `ValueError` explicitement plutôt que d'être ignorée en silence (une
    valeur mal formée est une erreur de l'appelant, pas un cas normal)."""
    result = default_levers()
    for code, raw_value in raw_levers.items():
        lever = _BY_CODE.get(code)
        if lever is None:
            continue
        try:
            value = Decimal(str(raw_value))
        except Exception as exc:  # noqa: BLE001 — reraised explicitement ci-dessous
            raise ValueError(f"Valeur de levier invalide pour '{code}' : {raw_value!r}") from exc
        result[code] = max(lever.min_value, min(lever.max_value, value))
    return result


def catalog_as_dicts() -> list[dict[str, Any]]:
    """Représentation JSON-serialisable du catalogue, pour l'écran atelier
    de scénarios (rendu des curseurs) et pour le schéma `parameters_schema`
    de l'outil IA `simulation.propose_scenario` (SIM-8)."""
    return [
        {
            "code": lever.code,
            "family": lever.family,
            "label": lever.label,
            "unit": lever.unit,
            "min": lever.min_value,
            "max": lever.max_value,
            "default": lever.default,
        }
        for lever in LEVER_CATALOG
    ]
