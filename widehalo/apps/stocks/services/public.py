"""Contrat public de l'app `stocks` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

ST1 du sous-sequencement (cf. plan) : rien a exposer pour l'instant
(`StkWarehouse`/`StkLocation`/`StkDefectType` sont encore une configuration
interne, consommee uniquement par les ecrans/API de `stocks` lui-meme). Ce
fichier existe des ST1, meme vide de fonctions, pour que `logistics`
(consommateur principal prevu par le plan) et le chantier retroactif de
comblement des stubs deja documentes dans `sales`/`purchase`/`accounting`
(stock stube a zero en PU8, valorisation stube en PU6/PU7) puissent s'y
brancher plus tard sans devoir le creer a ce moment-la."""

from __future__ import annotations
