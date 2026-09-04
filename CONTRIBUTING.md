# Contribuer

## Commits

Ce dépôt suit [Conventional Commits](https://www.conventionalcommits.org/) :
`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`.

## Règles de couplage entre apps

- Une app métier ne peut jamais importer les **modèles** d'une autre app
  métier — uniquement `core` et les **services publics** exposés via
  `apps.<module>.services.public`.
- Toute dépendance vers une autre app est déclarée explicitement dans
  `apps/<module>/module.py` (`ModuleSpec.dependencies`).
- `widehalo/tests/architecture/test_module_boundaries.py` fait échouer la CI
  en cas de violation — ne jamais le désactiver ou l'affaiblir pour
  contourner un blocage ponctuel.
- `widehalo/tests/architecture/test_budget.py` fait échouer la CI si le
  nombre de modèles/endpoints/écrans dépasse les plafonds V1 (180/600/90).

## Style de code

- `ruff format` (ligne 100), `ruff check` avant tout commit.
- `mypy --strict` sur `services/*.py` et `schemas.py` de chaque app.
- Clés primaires UUIDv7, jamais d'auto-incrément exposé.
- Suppression toujours logique (`is_active` + `archived_at`), jamais physique.
- Montants en `DecimalField(max_digits=18, decimal_places=4)`, jamais `float`.

## Revue de code

- À chaque **jour de durcissement** (cf. gabarit de sprint,
  `docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md` §3) : relire
  les docstrings qui décrivent une « limitation connue »/un comportement
  pas encore câblé sur les fichiers touchés par le sprint — un module câblé
  entre-temps à un autre laisse souvent un commentaire périmé qui affirme
  encore l'ancienne limitation (déjà relevé et corrigé sur
  `apps/sales/services/orders.py::mark_delivered`,
  `apps/accounting/services/landed_costs.py` et
  `apps/purchase/tests/test_acceptance.py`). Corriger ces docstrings fait
  partie du sprint, pas une tâche séparée à reporter.
