# WideHalo

ERP nouvelle génération (Python/Django) pour des PME malgaches textile et
agroalimentaire (importation de matières premières, manufacture,
transformation, distribution) — succession de l'ERP WideHalo existant
(Laravel).

## État du projet face aux cahiers des charges

Le projet est cadré par **quatre cahiers des charges officiels** du maître d'ouvrage
(Life MDG), dont le texte intégral est versionné dans
[`docs/cdc-complet/`](docs/cdc-complet/README.md) — 203 critères d'acceptation. Chacun
est confronté au code réel, fichier par fichier, par
[`docs/audit/2026-09-audit-complet-phases-1-4.md`](docs/audit/2026-09-audit-complet-phases-1-4.md)
(2026-09-05), qui remplace les deux audits antérieurs.

| Phase | Périmètre | Critères | ✅ | 🟡 | ❌ |
|---|---|---|---|---|---|
| **1** | Socle UX, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, IA | 52 | 25 | 19 | 6 |
| **2** | Business Intelligence, Forecast, Strategy, WhatsApp (sur entrepôt en étoile + dictionnaire d'indicateurs) | 38 | 24 | 11 | 2 |
| **3** | Stock et entrepôt, Achats/Import/CREDOC, Production, Qualité et HACCP, Paie, extension Forecast | 59 | 44 | 12 | 1 |
| **4** | Socle de flux, API publique, e-facture, encaissement mobile, flux bancaires, bureautique, commerce, console de flux | 54 | 1 | 16 | 37 |
| | | **203** | **94** | **58** | **46** |

Plus 3 critères non vérifiables et 2 sans objet. Le plan de fermeture — 16 lots de
rattrapage pour les Phases 1 à 3, puis les 34 sprints de la Phase 4 — est dans
[`docs/planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md`](docs/planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md).

**Deux points à connaître avant de lire un ✅ :**

1. **Rien n'ordonnance rien.** Les 51 commandes de gestion périodiques
   (rafraîchissement de l'entrepôt analytique, diffusions BI, alertes de péremption,
   contrôles qualité en retard…) n'ont aucun ordonnanceur : ni cron, ni service dans
   `docker-compose.prod.yml`, ni `Schedule` django-q2. En exploitation, BI, Forecast
   et Strategy travaillent donc sur des données vides. C'est le premier lot du plan.
2. **Ne jamais se fier à un chiffre de documentation sans le re-vérifier.** Les
   compteurs de modèles/endpoints/écrans ne font foi que ré-exécutés
   (`widehalo/tests/architecture/test_budget.py`, méthode dans
   `docs/planning/ECART_ARCHITECTURE.md` §1). Plafonds CI actuels, eux vérifiables
   dans le code : **310 / 600 / 240** (`widehalo/config/settings/base.py:412-414`).
   Une mesure statique du 2026-09-05 situe les écrans **à 240, soit le plafond exact**
   — le prochain gabarit ajouté fait échouer la construction sans relèvement.

Modules métier sous `widehalo/apps/` : `accounting`, `ai`, `analytics`, `automation`,
`bi`, `catalog`, `chat`, `crm`, `feasibility`, `financing`, `forecast`, `helpdesk`,
`logistics`, `mrp`, `partners`, `patronage`, `payroll`, `pos`, `presence`, `projects`,
`purchase`, `quality`, `reporting`, `sales`, `simulation`, `stocks`, `strategy`,
`whatsapp` — plus le socle `core`. Voir [`docs/RBAC.md`](docs/RBAC.md) pour les rôles
et permissions par module.

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
