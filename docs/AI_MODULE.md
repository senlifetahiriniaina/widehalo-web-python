# Le module `ai` fournit six fonctionnalités IA transversales, toujours avec un mode de repli sans coût ni dépendance réseau

Ce document décrit le module `ai` (assistant contextuel, détection d'anomalies,
recherche en langage naturel, insights proactifs, cache de prompts, advisor
d'actions), les trois modes de déploiement du connecteur IA sous-jacent et
leurs compromis explicites, et comment configurer chacun via
`settings.AI_PROVIDER_CONFIG`.

## 1. Principe directeur : fallback-first

Le connecteur générique (`apps.core.services.ai_assistant.get_ai_provider`,
chantier `projects`/PJ12, réutilisé tel quel par tout le module `ai`) renvoie
un `StubAIProvider` — **zéro appel réseau** — tant que
`settings.AI_PROVIDER_CONFIG` ne fournit pas explicitement `base_url` ET
`api_key`. Toute fonctionnalité IA de ce dépôt garde donc un comportement
utile même sans aucun fournisseur configuré : jamais une erreur HTTP 500,
toujours un résultat déterministe ou un texte de repli statique. Le budget de
tokens mensuel par tenant (`AiUsageLimit`/`AiRequest`, cf. § 6) s'ajoute
au-dessus de ce mécanisme : au-delà du seuil avec `hard_stop=True`,
`apps.ai.services.usage_budget.get_budget_gated_provider` bascule sur le stub
**avant même d'appeler `get_ai_provider()`** — aucun appel réseau facturé
n'est jamais déclenché au-delà du budget.

## 2. Les trois modes de déploiement

### 2.1. Mode 1 — Stub par défaut (recommandé pour démarrer)

`AI_PROVIDER_CONFIG = {}` (valeur par défaut de `config/settings/base.py`,
aucune modification nécessaire).

- **Coût** : zéro.
- **Dépendance réseau** : aucune.
- **Ce qui reste actif** : la détection d'anomalies déterministe (§ 4.2,
  jamais confiée à un LLM) et la guidance contextuelle statique fr/en par
  module (§ 4.1) continuent de fonctionner intégralement.
- **Ce qui est absent** : aucune prose générée par un LLM nulle part (pas de
  narrative d'anomalie, pas de synthèse d'insight, pas d'extraction de
  filtres sur la recherche en langage naturel) — chaque fonctionnalité
  dégrade silencieusement vers son résultat déterministe/statique.

### 2.2. Mode 2 — API hébergée low-cost (DeepSeek/Kimi) — mode recommandé

```python
AI_PROVIDER_CONFIG = {
    "backend": "deepseek",  # ou "kimi" — purement informatif, cf. § 3
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-...",
    "model": "deepseek-chat",
}
```

- **Coût** : quelques centimes par requête (facturation à l'usage du
  fournisseur), négligeable face au budget infra ≤60€/mois déjà acté pour ce
  dépôt.
- **Infra supplémentaire** : aucune — un simple appel HTTP sortant vers
  l'API du fournisseur.
- **Compromis** : dépendance à un service tiers externe (disponibilité,
  latence réseau normale d'un appel API distant).
- **C'est le mode par défaut recommandé** dès qu'une vraie prose générée est
  souhaitée (décision actée avec l'utilisateur au cadrage de ce chantier) :
  meilleur rapport coût/simplicité, aucune infrastructure à opérer.
- Kimi (Moonshot AI) fonctionne à l'identique avec
  `base_url="https://api.moonshot.cn/v1"` et `model="moonshot-v1-8k"` (ou
  équivalent) — même connecteur `OpenAICompatibleAIProvider`, aucun code
  spécifique par fournisseur.

### 2.3. Mode 3 — Auto-hébergé local (Ollama, profil Docker optionnel)

```python
AI_PROVIDER_CONFIG = {
    "backend": "local-ollama",
    "base_url": "http://ai-runtime:11434/v1",
    "api_key": "ollama",  # valeur factice non vérifiée par Ollama, mais
                          # requise NON VIDE par OpenAICompatibleAIProvider
    "model": "qwen2.5:7b",
}
```

Démarrage du conteneur (jamais lancé par un simple `docker compose up` —
c'est la toute première utilisation d'un **profil Docker Compose** dans ce
dépôt) :

```bash
docker compose --profile local-ai up -d ai-runtime
# premier démarrage uniquement : télécharger le modèle choisi (plusieurs Go)
docker compose exec ai-runtime ollama pull qwen2.5:7b
```

- **Coût récurrent** : zéro (aucune facturation à l'usage), au prix d'un
  matériel serveur suffisant.
- **Matériel nécessaire** : RAM/CPU conséquents pour un modèle 7B en
  inférence CPU (voire un GPU pour de meilleures performances) — à évaluer
  selon la charge réelle attendue, aucun chiffrage universel ici.
- **Latence** : nettement plus élevée qu'une API hébergée optimisée sur
  matériel dédié, surtout en inférence CPU pure.
- **Premier démarrage lent** : le téléchargement initial du modèle (`ollama
  pull`) peut prendre plusieurs minutes selon la bande passante — c'est
  pourquoi les poids sont persistés dans le volume nommé `ollama_data`
  (`docker-compose.yml`), jamais retéléchargés à chaque redémarrage du
  conteneur.
- **Pour qui** : celui qui dispose du matériel et veut une indépendance
  totale vis-à-vis de tout fournisseur externe (aucune donnée envoyée à un
  tiers).
- **Modèle par défaut disclosed** : `qwen2.5:7b` (modèle ouvert,
  raisonnablement exploitable sur un CPU modeste sans GPU dédié). Changeable
  via la variable d'environnement `OLLAMA_MODEL` du service
  `ai-runtime` — cette variable est purement documentaire pour le choix du
  modèle à télécharger manuellement (l'image `ollama/ollama` ne démarre
  aucun modèle automatiquement au lancement du conteneur) ; `deepseek-r1:7b`
  est une alternative plus lourde si le matériel le permet.
- L'API exposée par Ollama sur `/v1/chat/completions` est compatible OpenAI
  — le même connecteur `OpenAICompatibleAIProvider` que les modes 1-2
  fonctionne sans aucune adaptation.

## 3. La clé `"backend"` de `AI_PROVIDER_CONFIG`

Purement informative — jamais lue par `get_ai_provider()` pour décider quel
connecteur instancier (seuls `base_url`/`api_key` en décident). Elle est
lue par `apps.ai.services.usage_budget._resolve_backend_label` pour peupler
`AiRequest.provider_backend` à des fins de diagnostic/coût (savoir, après
coup, quel fournisseur a réellement traité chaque requête journalisée) —
valeurs libres suggérées : `"deepseek"`, `"kimi"`, `"local-ollama"`,
`"custom"` ; `"stub"` est renseignée automatiquement quand aucun fournisseur
réel n'est configuré, indépendamment de cette clé.

## 4. Récapitulatif des fonctionnalités IA1 à IA7

### 4.1. Assistant contextuel par page (`POST /api/v1/ai/assist`, AI2)

Guidance courte (3-5 lignes) par module métier, résolue via
`apps.core.services.ai_context_registry` (chaque module s'enregistre depuis
son propre `apps.py::ready()`). Sans fournisseur réel configuré (ou budget
épuisé) : texte statique fr/en garanti. Avec un fournisseur réel disponible :
le texte statique et un contexte optionnel enrichi
(`context_builder(tenant_id)`, ex. capacité atelier `mrp`) sont envoyés au
LLM pour une réponse plus riche — toute erreur réseau/API dégrade
silencieusement vers le texte statique. Réponse toujours accompagnée d'un
champ `is_ai_generated`. Cache Redis 300s. Endpoint ouvert à tout utilisateur
authentifié (même posture que `chat`), aucune permission RBAC dédiée.

### 4.2. Détection d'anomalies cross-module (`POST /api/v1/ai/anomalies/detect`, `GET /api/v1/ai/anomalies`, AI3)

Boucle sur `apps.core.services.anomaly_registry` : chaque vérification est
une fonction **déterministe** déjà branchée sur un calcul métier existant
(écart budgétaire `accounting`, stock négatif `stocks`, conflit de
planification `projects`, écart de prévision `sales`) — jamais une détection
confiée à un LLM. Une narrative en prose optionnelle (`ai_narrative`) n'est
générée que pour les anomalies de sévérité `haute`, et uniquement si un
fournisseur réel est disponible. Administration réservée à `admin`/
`direction` (`ai.view_aianomaly`/`ai.add_aianomaly`).

### 4.3. Recherche en langage naturel (`POST /api/v1/ai/search`, AI4)

Route **toujours** la question à travers `core.services.search.global_search`
déjà tenant-scopé et RBAC-filtré — jamais de SQL généré par un LLM ni de
requête brute construite depuis une sortie LLM (décision actée au cadrage,
déviation assumée du spec source qui décrivait un `NlToSqlService`). En
option, si un fournisseur réel est disponible, une extraction de filtres
structurés (`module`/`date_from`/`date_to`/`amount_threshold`) est tentée
contre une liste blanche stricte ; seul `module` est aujourd'hui réellement
appliqué au filtrage des résultats. Endpoint ouvert à tout utilisateur
authentifié.

### 4.4. Insights automatisés proactifs (`POST /api/v1/ai/insights/generate`, `GET /api/v1/ai/insights`, AI5)

Boucle sur `apps.core.services.insight_source_registry` : chaque source est
un calcul déterministe déjà existant (angle positif de prévision `sales`,
tendance de charge `strategy`, tendance d'absentéisme `presence`). Si au
moins deux modules distincts contribuent ET qu'un fournisseur réel est
disponible, une seule synthèse qualitative en prose relie les insights
générés — jamais un coefficient statistique inventé. Une notification
`direction` unique par appel. Endpoint ouvert à tout utilisateur authentifié.

### 4.5. Cache de prompts (`apps/ai/services/prompt_cache.py`, AI6)

Wrapper mince autour de `django.core.cache.cache` (même idiome que
`apps.core.throttling`), formalisant le mécanisme déjà utilisé ad hoc par
l'assistant contextuel (§ 4.1) : construction de clé lisible, hash stable
d'un payload, TTL configurable (300s par défaut). Pas de service dédié pour
AI3/AI4/AI5 — chacun de leurs calculs varie par exécution/par requête, un
cache n'y apporterait aucun gain (disclosed explicitement au chantier).

### 4.6. Advisor d'actions — next-best-action (`POST`/`GET /api/v1/ai/recommendations`, AI7)

Règles déterministes simples par contexte module/action/rôle (**pas un
modèle ML, aucun appel LLM**) via `apps.core.services.advisor_rule_registry`,
combinées aux actions déjà enregistrées dans
`apps.core.services.automation_registry` pour le module courant (une action
déjà automatisable est une candidate naturelle de suggestion). 2-3
suggestions par contexte. Endpoint ouvert à tout utilisateur authentifié.

## 5. Budget de tokens par tenant (AI1)

`AiUsageLimit` (`monthly_token_budget`, `alert_threshold_pct` défaut 80,
`hard_stop` défaut `True`) et `AiRequest` (journal d'audit,
`provider_backend`, estimation approximative de tokens par nombre de mots ×
facteur — disclosed comme non-exacte, aucun tokenizer précis n'est
disponible sans dépendance supplémentaire au fournisseur réel). Tableau de
bord : `GET /ai/usage/`. Administration (`GET`/`POST /api/v1/ai/usage/budget`,
`GET /api/v1/ai/usage`) réservée à `admin`/`direction` — pilotage de coût,
pas une opération courante des autres rôles.

## 5bis. Passerelle IA locale d'analyse de données conversationnelle (GW1-GW5)

Extension du module `ai` distincte des fonctionnalités AI1-AI7 ci-dessus : au
lieu d'une prose générée librement, `POST /api/v1/ai/data-query/ask`
(`GET /ai/data-query/` côté écran) laisse un LLM répondre à une question en
langage naturel sur les données du tenant (« quel est le CA du mois dernier
par client ? ») en choisissant, via le protocole standard de "tool calling"
compatible OpenAI, parmi une **liste blanche explicite et restreinte** de
rapports déjà construits et testés — **jamais de génération de SQL, jamais
d'accès direct à un modèle Django depuis le LLM**.

**Décision architecturale** : code Django intégré à `apps.ai`, appelant en
processus les fonctions déjà existantes de `services/reports.py` (zéro appel
réseau supplémentaire, zéro nouveau service à déployer) — pas de microservice
séparé. Le seul service Docker satellite reste le conteneur Ollama du § 2.3.

**Catalogue de tools (`apps.core.services.data_query_tool_registry`)** :
chaque tool (`sales.revenue_report`, `sales.margin_report`,
`stocks.stock_state_rows` dans ce premier lot) porte un `required_permission`
explicite. **Le catalogue est filtré aux tools que l'utilisateur authentifié
peut réellement utiliser AVANT d'être présenté au LLM** — un tool hors
permission n'est jamais même proposé comme option, pas seulement bloqué après
coup (même philosophie deny-by-default que le reste du RBAC de ce dépôt).
`sales.margin_report` illustre cette discipline : il transmet les rôles réels
de l'utilisateur courant, respectant le même masquage par rôle
(`margin_pct`/`cost_estimate_mga`, RG-SAL-5) que l'écran/l'export classiques.

**Fonctionnement** : même discipline "fallback-first" que AI2-AI7
(`get_budget_gated_provider`) — sans fournisseur réel configuré (ou budget
épuisé), une réponse statique est renvoyée immédiatement, la boucle de
tool-calling n'est jamais tentée. Avec un fournisseur réel, une boucle
d'échanges question/tool-calls est bornée à 3 allers-retours maximum pour
garantir sa terminaison, quel que soit le comportement du modèle. Fonctionne
identiquement avec le Mode 2 (API hébergée) et le Mode 3 (Ollama local,
`qwen2.5:7b` supportant déjà le tool-calling) — même connecteur
`OpenAICompatibleAIProvider`, aucune adaptation par mode. Chaque session est
journalisée dans `AiDataQuery` (question, tools réellement invoqués, réponse).

## 6. Recommandation opérationnelle

Démarrer en mode 1 (stub, § 2.1) tant qu'aucune fonctionnalité générative
n'est requise. Passer en mode 2 (§ 2.2, DeepSeek/Kimi) dès qu'une prose
générée devient utile — c'est le mode recommandé par défaut pour la
production, coût marginal et zéro infrastructure à opérer. Réserver le mode
3 (§ 2.3, Ollama auto-hébergé) au cas où l'indépendance totale vis-à-vis de
tout fournisseur externe prime sur la latence et le coût matériel.
