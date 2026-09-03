"""Registre statique {code indicateur -> nom de fait de l'entrepôt} — la
partie « où le calculer » de chaque indicateur du dictionnaire gouverné
(cf. `apps.analytics.models.AnMetricDefinition`, qui ne porte que la partie
« comment le décrire » : `formule` y est un TEXTE humain, jamais du code
exécutable, cf. sa docstring).

L'agrégation elle-même (champs/axes réellement exposables) est déclarée et
exécutée DANS `apps.analytics` (`services/fact_specs.py` + `services.
public.aggregate_fact`/`detail_fact`) — jamais ici : `bi` ne doit jamais
importer `apps.analytics.models` directement (règle de couplage n°1,
`tests/architecture/test_module_boundaries.py`), seulement son
`services/public.py`. Ce module ne fait que faire correspondre un code
d'indicateur du dictionnaire à un nom de fait connu de `analytics` — un
code présent dans le dictionnaire mais absent d'ici n'est pas (encore) un
indicateur BI-consommable, `services/query.py` l'exclut silencieusement
du rapport plutôt que de lever une exception."""

from __future__ import annotations

METRIC_FACTS: dict[str, str] = {
    "sales.ca_ht": "vente",
    "pos.ca_ttc": "ticket_pos",
    "accounting.encaissements": "encaissement",
    "accounting.solde_compte": "ecriture",
}
