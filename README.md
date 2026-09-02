# WideHalo

ERP nouvelle génération (Python/Django) pour une PME textile malgache
(importation de matières premières, manufacture, distribution) —
succession de l'ERP WideHalo existant (Laravel).

## Périmètre de ce lot

Ce dépôt a livré le **Lot 1** (socle technique transversal : multi-tenant,
authentification, RBAC, i18n, API, workflow, événements, tâches
asynchrones, chat interne, documents, audit, recherche, notifications,
import/export, référentiels partagés `partners` et `catalog`) et est
maintenant engagé dans le **Lot 2 Madagascar** : plusieurs modules métier
complets sont déjà livrés (`accounting`, `stocks`, `presence`, `payroll`,
`projects`, `purchase`, `helpdesk`, entre autres — voir
`config/settings/base.py::BUDGET_MAX_MODELS` pour l'historique des
chantiers clôturés). Voir le cahier des charges pour la feuille de route
complète et `docs/planning/ECART_ARCHITECTURE.md` pour l'état réel mesuré
du dépôt (modèles/endpoints/écrans) face aux budgets déclarés.

## Démarrage

```bash
cp .env.example .env
docker compose up --build
```

L'application est ensuite disponible sur http://localhost:8000, l'API sur
http://localhost:8000/api/v1/docs.

## Développement

```bash
make lint        # ruff check + format --check
make typecheck    # mypy --strict sur services/ et schemas.py
make test         # pytest (couverture)
```

## Déploiement

Pour déployer sur un VM Hetzner (sous-domaine + certificat SSL automatique
via Caddy/Let's Encrypt), voir [`docs/DEPLOYMENT_HETZNER.md`](docs/DEPLOYMENT_HETZNER.md).

## Architecture

Monolithe modulaire Django (« modulith ») : voir `widehalo/apps/core/module.py`
et `widehalo/tests/architecture/` pour les règles de couplage inter-modules
appliquées automatiquement en CI.
