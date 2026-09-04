# WideHalo

ERP nouvelle génération (Python/Django) pour des PME malgaches textile et
agroalimentaire (importation de matières premières, manufacture,
transformation, distribution) — succession de l'ERP WideHalo existant
(Laravel).

## État du projet face aux cahiers des charges

Le projet est cadré par trois cahiers des charges officiels du maître
d'ouvrage (Life MDG), chacun confronté au code réel par un audit sourcé
fichier par fichier plutôt que par une simple déclaration de statut :

| Phase | Périmètre | État | Audit |
|---|---|---|---|
| **Phase 1** | Socle UX, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, IA | Modules livrés (POS et Simulation financière, initialement absents, ont été construits depuis) | [`docs/audit/2026-09-cahier-des-charges-v3-audit.md`](docs/audit/2026-09-cahier-des-charges-v3-audit.md) |
| **Phase 2** | Business Intelligence, Forecast, Strategy, WhatsApp (sur un entrepôt analytique en étoile + dictionnaire d'indicateurs) | Modules livrés depuis le même audit (`analytics`, `bi`, `forecast`, `strategy`, `whatsapp`) | même document |
| **Phase 3** | Stock et entrepôt, Achats/Import/CREDOC, Production, Qualité et HACCP, Paie, extension Forecast | Cahier reçu le 2026-09-04 ; le dépôt couvre déjà une bonne partie de ce périmètre sous des modules construits antérieurement et indépendamment (`stocks`, `purchase`, `mrp`, `payroll`, `presence`) — **8 des 59 critères d'acceptation du cahier sont conformes, 27 partiels, 21 absents**, dont deux violations concrètes de règles explicites (double comptabilité de quantité stock/achats, portail salarié alors qu'explicitement interdit) | [`docs/audit/2026-09-cahier-des-charges-v3-phase3-audit.md`](docs/audit/2026-09-cahier-des-charges-v3-phase3-audit.md) |

**Ne jamais se fier à un chiffre de documentation sans le re-vérifier** :
les compteurs de modèles/endpoints/écrans ne font foi que ré-exécutés
(`docs/planning/ECART_ARCHITECTURE.md` §1) — au 2026-09-04 : **290 modèles
/ 569 endpoints / 238 écrans**, contre un plafond CI de 290/600/240 (le
plafond « modèles » est atteint exactement, marge nulle).

Modules métier existants sous `widehalo/apps/` : `accounting`, `ai`,
`analytics`, `bi`, `catalog`, `crm`, `feasibility`, `financing`,
`forecast`, `helpdesk`, `logistics`, `mrp`, `partners`, `patronage`,
`payroll`, `pos`, `presence`, `projects`, `purchase`, `reporting`,
`sales`, `simulation`, `stocks`, `strategy`, `whatsapp` — voir
[`docs/RBAC.md`](docs/RBAC.md) pour le détail des rôles et permissions par
module.

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
