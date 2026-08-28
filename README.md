# WideHalo

ERP nouvelle génération (Python/Django) pour une PME textile malgache
(importation de matières premières, manufacture, distribution) —
succession de l'ERP WideHalo existant (Laravel).

## Périmètre de ce lot

Ce dépôt contient le **Lot 1** : socle technique transversal (multi-tenant,
authentification, RBAC, i18n, API, workflow, événements, tâches
asynchrones, chat interne, documents, audit, recherche, notifications,
import/export) et les référentiels partagés `partners` et `catalog`.
Aucun module métier complet (comptabilité, ventes, etc.) n'est livré dans
ce lot — voir le cahier des charges pour la feuille de route complète.

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
