# WideHalo v3 — Cahier des charges Phase 1

*Refonte de l'expérience utilisateur de l'ERP WideHalo*

**PHASE 1 — CRM • Sales • Accounting (PCG 2005) POS • Simulation financière • IA**

| Rubrique | Valeur |
|---|---|
| PROJET | WideHalo — ERP PME |
| DOCUMENT | Cahier des charges |
| VERSION | 3.0 — Phase 1 |
| MAÎTRE D'OUVRAGE | Life MDG |
| ZONE CIBLE | Madagascar (PCG 2005) |
| DATE | Septembre 2026 |
| MODE DE DÉVELOPPEMENT | Solo assisté IA (Claude Code) |
| DURÉE PHASE 1 | 29 sprints hebdomadaires |
| STATUT | Pour validation |

- **1. Résumé exécutif**
  - Les six décisions structurantes
  - Périmètre de ce document
- **2. Contexte, objectifs et périmètre**
  - 2.1 Contexte du projet
  - 2.2 Objectifs de la version 3
  - 2.3 Découpage en phases
  - 2.4 Périmètre inclus — Phase 1
  - 2.5 Périmètre exclu — hors Phase 1
- **3. Utilisateurs cibles et cas d'usage**
  - 3.1 Cas d'usage principaux de la Phase 1
  - 3.2 Conditions d'usage à ne pas sous-estimer
- **4. Contraintes du projet**
  - 4.1 Hypothèses ouvertes à lever
- **5. Architecture applicative**
  - 5.1 Couche présentation
  - 5.2 Couche logique métier
  - 5.3 Couche données et persistance
  - 5.4 Couche intégration
  - 5.5 Couche infrastructure et déploiement
  - 5.6 Couche transverse
- **6. Sécurité**
  - 6.1 Authentification
  - 6.2 Autorisation
  - 6.3 Chiffrement et secrets
  - 6.4 Sécurité applicative
  - 6.5 Audit et traçabilité
- **7. UX/UI et confort d'usage**
  - 7.1 Ce que l'on emprunte, et ce que l'on refuse
  - 7.2 Sept principes vérifiables
  - 7.3 Architecture d'information et navigation
  - 7.4 Design system
  - 7.5 Bibliothèque de composants à construire
  - 7.6 Performance perçue et réseau dégradé
  - 7.7 Internationalisation
- **8. Gouvernance des données**
  - 8.1 Classification
  - 8.2 Cycle de vie et rétention
  - 8.3 Conformité
  - 8.4 Qualité des données
  - 8.5 Sauvegarde et reprise
- **9. Interopérabilité et outils tiers**
  - 9.1 Gouvernance des échanges
- **10. Scalabilité**
  - 10.1 Budgets d'architecture révisés
- **11. Choix technologiques**
  - 11.1 Architecture de la couche présentation
  - 11.2 Bibliothèque de composants visuels
  - 11.3 Composants confirmés sans réexamen
- **12. Socle transverse et référentiel comptable**
  - 12.1 Moteurs génériques
  - 12.2 Abstraction du référentiel comptable
  - 12.3 Paramètres réglementaires versionnés
- **13. Spécifications fonctionnelles — Phase 1**
  - 13.1 Module CRM
  - 13.2 Module Sales
  - 13.3 Module Accounting
  - 13.4 Module IA — copilote WideHalo
  - 13.5 Module POS — distribution et services
  - 13.6 Module Simulation financière temps réel
- **14. Plan de développement — sprints hebdomadaires**
  - 14.1 Ordonnancement et dépendances
  - 14.2 Bloc A — Cadrage et socle UX (S1 à S8)
  - 14.3 Bloc B — Module CRM (S9 à S11)
  - 14.4 Bloc C — Module Sales (S12 à S15)
  - 14.5 Bloc D — Module Accounting (S16 à S19)
  - 14.6 Bloc E — Module POS (S20 à S23)
  - 14.7 Bloc F — Simulation financière (S24 à S26)
  - 14.8 Bloc G — Module IA (S27 et S28)
  - 14.9 Bloc H — Durcissement et mise en production (S29)
  - 14.10 Répartition du travail humain / assistant IA
- **15. Estimation détaillée**
  - 15.1 Hypothèses de l'estimation
  - 15.2 Synthèse par bloc
  - 15.3 Lecture des deux unités
  - 15.4 Trois scénarios
  - 15.5 Marges appliquées par type de tâche
- **16. Risques et plan de mitigation**
- **17. Critères de recette et métriques de succès**
  - 17.1 Recette fonctionnelle
  - 17.2 Recette technique — barrières bloquantes
  - 17.3 Métriques d'expérience utilisateur
  - 17.4 Conditions de mise en production
- **18. Annexes**
  - 18.1 Glossaire
  - 18.2 Documents de référence
  - 18.3 Suites immédiates

## 1. Résumé exécutif

Ce qu'il faut retenir en une page

WideHalo est l'ERP développé et commercialisé par **Life MDG** à destination des PME malgaches des filières **textile** (importation, manufacture, distribution) et **agroalimentaire** (production, transformation, distribution). Le produit dispose déjà d'une base fonctionnelle riche : les workflows, les structures de données et la couverture métier sont proches de la cible. Le frein à l'adoption n'est pas la fonctionnalité, c'est **l'expérience utilisateur**.

La version 3 est donc une **refonte d'expérience**, pas une réécriture. Environ 70 % de l'effort porte sur la couche présentation (design system, bibliothèque de composants, navigation par rôle, vues configurables) et 30 % sur des moteurs applicatifs transverses identifiés par comparaison avec HubSpot, Odoo et SAP Fiori. Le backend Django et le modèle de données métier sont conservés.

## 74,5

### Les six décisions structurantes

1. **WideHalo est le nom unique du produit.** Le nom de projet « ORION » est abandonné ; le dépôt widehalo-web-python@madagascar1 devient la base de code unique. Toute référence à ORION dans le code, les dépôts, les conteneurs et la documentation est renommée (y compris orion-ai-gateway → widehalo-ai-gateway).
2. **Le PCG 2005 devient le référentiel comptable de première classe.** Le code d'origine a été conçu « OHADA first » (SYSCOHADA), ce qui est incompatible en l'état avec Madagascar. La Phase 1 introduit une couche d'abstraction du référentiel comptable qui rend le PCG 2005 natif, SYSCOHADA restant activable par pays pour la roadmap OHADA (phase ultérieure).
3. **Aucun paramètre réglementaire n'est codé en dur.** Taux de TVA, barème IRSA, taux CNaPS et OSTIE, plafonds, SME : tout vit dans une table versionnée core_regulatory_parameter avec date d'effet, source et champ de validation par un expert-comptable membre de l'OECFM avant mise en production.
4. **La migration se fait écran par écran (strangler pattern).** L'ancienne et la nouvelle interface coexistent derrière un routage à feature flags, sur un backend partagé. Toute nouvelle fonctionnalité va exclusivement dans la nouvelle UI, et chaque écran migré déclenche la suppression de son équivalent legacy.
5. **L'IA n'accède jamais à la base de données.** Le copilote passe par un microservice gateway qui appelle une liste blanche d'endpoints en lecture seule via function-calling. Le text-to-SQL est interdit par principe d'architecture, pas par précaution temporaire. Le même principe borne la simulation financière : l'IA peut paramétrer le moteur, elle ne produit jamais un chiffre.
6. **Le POS est conçu hors ligne d'abord, la simulation est conçue sans effet de bord.** Ce sont les deux exigences qui structurent les modules ajoutés à la Phase 1 : une caisse doit encaisser sans réseau ni électricité stable et se réconcilier sans doublon ; un scénario financier doit répondre en moins de 100 ms sans jamais créer ni modifier la moindre écriture.

### Périmètre de ce document

Ce document couvre **exclusivement la Phase 1**, c'est-à-dire le socle d'expérience utilisateur commun et les six modules prioritaires : **CRM**, **Sales**, **Accounting**, **POS**, **Simulation financière** et **IA**. Les phases 2 et 3 sont décrites uniquement pour situer la trajectoire produit et vérifier que les choix d'architecture de la Phase 1 ne les bloquent pas ; elles feront l'objet de cahiers des charges distincts.

**Limite de ce document à lever avant le sprint 2.** Le dépôt github.com/senlifetahiriniaina/widehalo-web-python (branche madagascar1) n'a pas pu être lu automatiquement lors de la rédaction : l'analyse du code réel (modèles, endpoints, écrans, état réel des modules) n'a donc pas été vérifiée dans les sources. Les affirmations concernant l'existant sont signalées **[HYPOTHÈSE]** dans tout le document. Le sprint 1 produit un fichier INVENTAIRE_EXISTANT.md qui devient le point de vérité et remplace ces hypothèses.

## 2. Contexte, objectifs et périmètre

Pourquoi cette refonte, pour qui, et jusqu'où

### 2.1 Contexte du projet

WideHalo est développé par un développeur solo sous la marque Life MDG, depuis Antananarivo, avec Claude Code comme assistant de développement principal. Le produit est auto-hébergé sur Hetzner Cloud via Coolify. Il vise des PME de 5 à 150 salariés, dans deux filières qui partagent une même logique de flux (achat/import → transformation → stock → vente) mais diffèrent sur la nature des contraintes : déclinaison taille/couleur et saisonnalité côté textile, traçabilité par lot et dates de péremption côté agroalimentaire.

L'historique du produit doit être rappelé car il conditionne la Phase 1 : la base de code a été conçue selon une logique « Africa first / OHADA first », adossée au référentiel comptable SYSCOHADA révisé. Or Madagascar n'est pas membre de l'OHADA et applique le Plan Comptable Général 2005. Cette incompatibilité n'est pas cosmétique : elle touche le plan de comptes, la structure des états financiers et la logique de paramétrage fiscal. C'est la raison pour laquelle le module Accounting figure en Phase 1 malgré son coût.

### 2.2 Objectifs de la version 3

| Objectif | Énoncé | Comment il est mesuré |
|---|---|---|
| **O1 — Adoption** | Rendre WideHalo utilisable par un utilisateur métier sans formation longue, au niveau de confort d'un outil grand public métier (HubSpot). | Score SUS ≥ 80 sur les parcours Phase 1 ; onboarding autonome réussi sans assistance. |
| **O2 — Efficacité** | Réduire le coût d'usage quotidien des tâches répétitives (saisie devis, saisie écriture, relance client). | – 30 % de temps par tâche et de nombre de clics sur 5 tâches de référence. |
| **O3 — Conformité** | Produire une comptabilité et une facturation conformes au PCG 2005 et à la réglementation fiscale malgache, avec un paramétrage auditable. | Validation écrite par un expert-comptable membre de l'OECFM avant mise en production. |
| **O4 — Robustesse d'usage** | Fonctionner correctement sur connexion lente ou instable et sur matériel modeste, en agence comme sur tablette. | Première interaction utile < 3 s sur profil réseau dégradé ; mode dégradé explicite. |
| **O5 — Effet de levier IA** | Donner à l'utilisateur un accès conversationnel à ses données, sans risque de fuite ni d'hallucination structurelle. | 100 % des réponses IA traçables à un appel d'outil journalisé ; zéro accès SQL direct. |
| **O6 — Soutenabilité solo** | Garder une base maîtrisable par un développeur seul malgré la richesse fonctionnelle. | Budgets d'architecture vérifiés en CI (modèles / endpoints / écrans) ; écrans legacy en décroissance forcée. |

### 2.3 Découpage en phases

Le découpage retenu suit une logique de valeur commerciale : la Phase 1 livre la chaîne « prospect → devis → commande → facture → écriture comptable », qui est le cœur démonstrable d'un ERP et le premier motif d'achat d'une PME, augmentée du copilote IA qui constitue le différenciateur perçu face à la concurrence.

| Phase | Modules | Rôle dans la trajectoire | Statut |
|---|---|---|---|
| **Phase 1** | Socle UX + CRM + Sales + Accounting (PCG 2005) + POS + Simulation financière + IA | Chaîne de valeur commerciale et comptable complète, encaissement au comptoir (distribution et services) et aide à la décision. Conformité malgache. Différenciateurs POS hors ligne, simulation temps réel et copilote IA. | Objet de ce document |
| **Phase 2** | Patronnage • Strategy • Forecast • Business Intelligence • WhatsApp | Métier textile amont, pilotage et prévision à moyen terme (qui s'appuiera sur le moteur de simulation livré en Phase 1), restitution décisionnelle, canal de communication local dominant. | Cahier des charges séparé |
| **Phase 3** | Achats/Import & CREDOC, Stock/Entrepôt, Production, Qualité/HACCP, Paie, et modules restants | Couverture ERP complète des deux verticales. | Cahier des charges séparé |

**Ce que la Phase 1 doit préparer sans le livrer.** Trois décisions de Phase 1 conditionnent directement les phases suivantes et doivent être prises correctement dès maintenant : (1) le **moteur de vues configurables**, qui permettra d'ajouter les écrans des phases 2 et 3 sans recoder un data grid à chaque fois ; (2) le **modèle de notification et de canal**, qui doit être abstrait dès la Phase 1 pour que WhatsApp (Phase 2) devienne un simple adaptateur ; (3) la **couche de paramètres réglementaires versionnés**, qui portera la paie (Phase 3) et la localisation OHADA. S'y ajoute désormais le **point d'accroche du POS au stock** : la sortie de caisse est enregistrée dès la Phase 1 comme mouvement indicatif, pour que le module Stock de la Phase 3 s'y branche sans reprise du modèle de vente.

### 2.4 Périmètre inclus — Phase 1

- **Socle UX transverse** : design system et jeu de design tokens, bibliothèque de composants, coquille applicative (shell), launchpad par rôle, fil d'Ariane, recherche globale, data grid universel, moteur de vues configurables, filtres sauvegardés, formulaires à validation en ligne, chatter et activités, notifications, préférences utilisateur, journal d'audit.
- **Module CRM** : sociétés, contacts, pistes, opportunités, pipeline kanban, activités et relances, segmentation, import/export, tableau de bord commercial.
- **Module Sales** : catalogue et tarification (y compris variantes textile et unités agroalimentaires), devis, commande client, bon de livraison, facture et avoir, acomptes, suivi des encaissements, TVA à 20 %.
- **Module Accounting** : abstraction du référentiel comptable, plan de comptes PCG 2005, journaux et écritures, lettrage, rapprochement bancaire, déclaration de TVA, états financiers (balance, grand livre, bilan, compte de résultat), clôture d'exercice, table de paramètres réglementaires versionnés.
- **Module POS** : points de vente et caisses, sessions de caisse, écran de vente tactile et clavier, paiements multi-moyens dont le mobile money, tickets et factures, retours et avoirs, prestations de service au forfait ou au temps passé, clôture avec écart et écriture consolidée, fonctionnement hors ligne avec synchronisation différée.
- **Module Simulation financière temps réel** : socle de simulation agrégé, moteur de recalcul immédiat, atelier de scénarios, projection de trésorerie à 13 semaines, point mort et sensibilité, bibliothèque et comparateur de scénarios.
- **Module IA** : microservice widehalo-ai-gateway, liste blanche d'outils en lecture seule, copilote intégré à l'interface, résumés et aides à la rédaction, garde-fous et journalisation.
- **Transverse** : multi-tenant et RLS, sécurité, i18n (français prioritaire), performance sur réseau faible, déploiement et observabilité.

### 2.5 Périmètre exclu — hors Phase 1

Un périmètre sans exclusions explicites dérive. Les points suivants sont volontairement hors Phase 1 :

- Modules Patronnage, Strategy, Forecast, Business Intelligence et WhatsApp (→ Phase 2).
- Achats/import et CREDOC, stock et entrepôt, production et ordres de fabrication, qualité et HACCP, paie et RH (→ Phase 3).
- Déploiement dans la zone OHADA et activation effective de SYSCOHADA : la Phase 1 livre l'abstraction qui le rendra possible, pas la localisation elle-même.
- Réécriture du modèle de données métier existant : il est conservé, sauf là où l'abstraction comptable l'impose.
- Applications mobiles natives : le responsive et le mode tablette couvrent le besoin.
- Text-to-SQL, génération automatique d'écritures comptables par l'IA, et toute action d'écriture déclenchée directement par le modèle de langage : exclu par principe, pas par phase.
- Migration de données depuis des ERP tiers : traitée en prestation, hors produit.
- Intégration matérielle avancée du POS (tiroir-caisse piloté, balance connectée, afficheur client) et intégration transactionnelle directe aux passerelles de mobile money : la Phase 1 se limite à l'imprimante ticket, au scanner et à la saisie de la référence de transaction.
- Vente en ligne et synchronisation avec une boutique e-commerce.
- Budget engagé et suivi budgétaire : la simulation produit des projections, jamais un budget opposable. Le rapprochement budget / réel relève de la Phase 2 (Strategy).

## 3. Utilisateurs cibles et cas d'usage

Qui utilise quoi, et dans quelles conditions réelles

Les personas ci-dessous ne sont retenus que pour leur pertinence en Phase 1. Les rôles opérationnels d'atelier et d'entrepôt (magasinier, responsable production, contrôleur qualité) existent dans la cible produit mais leurs écrans relèvent des phases 2 et 3 ; ils ne sont pris en compte ici que pour vérifier que le socle UX ne leur ferme aucune porte (densité d'information, tablette, cibles tactiles).

| Persona | Contexte d'usage réel | Attentes prioritaires Phase 1 | Écrans concernés |
|---|---|---|---|
| **Dirigeant PME** **Utilisateur occasionnel, souvent mobile** | Consulte 5 à 10 minutes par jour, souvent sur téléphone ou tablette, parfois en déplacement avec un réseau instable. | Voir l'état de l'entreprise sans cliquer : CA du mois, créances échues, trésorerie, affaires en cours. Poser une question en langage naturel plutôt que chercher un rapport. | Launchpad, copilote IA, tableau de bord commercial et comptable. |
| **Commercial** **Utilisateur intensif** | Passe la journée dans l'outil, alterne téléphone client et saisie. Interrompu en permanence. | Pipeline visuel, création d'un devis en moins de deux minutes, historique client complet sur un seul écran, relances qui ne s'oublient pas. | CRM (pipeline, fiche société), Sales (devis, commande), chatter et activités. |
| **Assistant(e) administration des ventes** **Utilisateur intensif** | Saisie répétitive à fort volume, forte exigence d'exactitude, travaille par lots. | Saisie clavier rapide sans passer par la souris, duplication d'un document existant, actions de masse, contrôles d'erreur immédiats plutôt qu'à l'enregistrement. | Sales (commande, BL, facture), grilles de données, imports. |
| **Comptable** **Utilisateur expert** | Travaille par période (clôture mensuelle, déclaration TVA), avec des exigences de conformité non négociables et un contrôle externe possible. | Plan de comptes PCG 2005 correct, saisie d'écriture dense et rapide, lettrage, états imprimables, traçabilité de toute modification. | Accounting (journaux, écritures, lettrage, TVA, états), audit. |
| **Expert-comptable externe (OECFM)** **Utilisateur ponctuel, à fort pouvoir de blocage** | Intervient en validation et en révision. Ne connaît pas l'outil et n'a pas de temps à y consacrer. | Retrouver immédiatement un compte, un journal, une pièce ; exporter ; vérifier que les paramètres fiscaux appliqués sont les bons, avec leur date d'effet. | Accounting (états, exports), écran de paramètres réglementaires, journal d'audit. |
| **Caissier / vendeur** **Utilisateur intensif, debout, en tension** | Encaisse face à une file d'attente, sur tablette ou poste tactile, avec un réseau et une électricité qui peuvent tomber à tout moment. Souvent peu formé, parfois saisonnier. | Encaisser vite, ne jamais rester bloqué, savoir immédiatement combien rendre, continuer à vendre même sans réseau, et clôturer sa caisse sans discussion sur l'écart. | POS (vente, paiement, session, ticket, retour). |
| **Contrôleur de gestion** **Utilisateur périodique, à fort pouvoir de décision** | Intervient en préparation de décision : négociation de prix, arbitrage d'investissement, tension de trésorerie. Travaille aujourd'hui dans un tableur déconnecté des données. | Manipuler des hypothèses sur les vraies données et voir l'effet immédiatement ; comparer des scénarios ; savoir de quand datent les chiffres qu'il manipule. | Simulation financière, rapports, copilote IA. |
| **Administrateur fonctionnel** **Un par client, souvent le dirigeant ou le comptable** | Configure l'outil au démarrage puis ponctuellement. | Créer des utilisateurs, attribuer des rôles, paramétrer les tuiles du launchpad, importer les données initiales sans intervention de l'éditeur. | Paramètres, rôles et permissions, imports. |

### 3.1 Cas d'usage principaux de la Phase 1

Ces sept parcours servent de tâches de référence pour la mesure de l'objectif O2 (– 30 % de temps et de clics). UC1 à UC5 sont chronométrés sur l'interface actuelle en sprint 1 pour établir la ligne de base ; UC6 et UC7 portant sur des modules nouveaux, leur référence est la pratique actuelle hors ERP (caisse manuelle, tableur), puis re-chronométrés à chaque livraison.

| Réf. | Parcours de référence | Acteur | Définition de fin |
|---|---|---|---|
| **UC1** | Qualifier un prospect entrant et planifier une relance | Commercial | Opportunité créée, rattachée à une société, avec une activité planifiée. |
| **UC2** | Établir un devis multi-lignes et l'envoyer au client | Commercial | Devis validé, PDF généré, envoi tracé dans le chatter. |
| **UC3** | Transformer un devis accepté en commande puis en facture | ADV | Facture émise, numérotée, TVA calculée, écriture comptable générée. |
| **UC4** | Saisir un relevé de banque et lettrer les règlements clients | Comptable | Écritures saisies, règlements lettrés, solde client à jour. |
| **UC5** | Répondre à une question de gestion sans ouvrir de rapport | Dirigeant | Réponse obtenue via le copilote, avec le lien vers la donnée source. |
| **UC6** | Encaisser une vente de trois articles en espèces, réseau coupé | Caissier | Ticket produit, monnaie rendue, vente en file de synchronisation. |
| **UC7** | Mesurer l'effet d'une baisse de prix sur la marge et la trésorerie à 13 semaines | Contrôleur de gestion | Scénario enregistré, écart chiffré vs référence, date des données source portée. |

### 3.2 Conditions d'usage à ne pas sous-estimer

- **Réseau** : les connexions professionnelles à Antananarivo sont correctes mais irrégulières, et deviennent lentes en province. Le dimensionnement se fait sur le pire cas raisonnable, pas sur le cas du bureau du développeur.
- **Matériel** : parc hétérogène, machines de bureau anciennes, navigateurs pas toujours à jour. Cela disqualifie une interface reposant sur un gros bundle JavaScript.
- **Coupures** : les interruptions d'électricité et de réseau sont fréquentes. Une saisie longue perdue faute de brouillon sauvegardé est un motif réel d'abandon de l'outil — et en point de vente, une caisse qui refuse d'encaisser pendant vingt minutes est un incident commercial, pas une gêne. C'est ce qui justifie la conception hors ligne du POS.
- **Langue** : le français est la langue de travail administrative et comptable. Le malgache devient pertinent dès la Phase 1 avec le POS, dont les utilisateurs sont les moins francophones du parc, ainsi que pour les rôles opérationnels des phases suivantes ; l'anglais pour un éventuel client export. L'internationalisation est préparée dès la Phase 1, même si seul le français est livré.

## 4. Contraintes du projet

Ce qui est imposé et non négociable

| Catégorie | Contrainte | Conséquence sur la conception |
|---|---|---|
| **Organisationnelle** | Un seul développeur, assisté par Claude Code, cumulant développement, gestion de projet, support et relation client. | Interdit les architectures à forte charge opérationnelle (microservices, Kubernetes). Impose des garde-fous automatisés (tests, budgets CI) plutôt que de la discipline humaine. |
| **Technique imposée** | Stack existante conservée : Python, Django 5.2 LTS, django-ninja, HTMX, Alpine.js, PostgreSQL. | La refonte UX se fait dans ce cadre : rendu serveur avec composants, pas de SPA. Le choix est réexaminé formellement en section 11 plutôt qu'accepté par défaut. |
| **Infrastructure** | Auto-hébergement Hetzner Cloud (CX43 production, CX33 secondaire), Coolify, Docker Compose, Caddy. Budget serré. | Le LLM tourne en local sur CPU (16 Go de RAM), sans GPU. Le dimensionnement IA doit en tenir compte, avec repli cloud à la demande. |
| **Réglementaire** | PCG 2005 (décret n° 2004-272 du 18 février 2004), fiscalité malgache, Ariary (MGA). Madagascar hors OHADA. | Référentiel comptable abstrait, paramètres versionnés, validation OECFM obligatoire avant production. |
| **Données** | Données comptables et commerciales de clients tiers, hébergées hors du territoire national (Allemagne/Finlande selon la région Hetzner). | Impose une information contractuelle explicite du client sur la localisation, un chiffrement au repos et en transit, et une politique de sauvegarde documentée. |
| **Produit** | Budgets d'architecture vérifiés en intégration continue (modèles, endpoints, écrans). | Toute nouvelle entité doit être justifiée. Le budget est révisé en section 10, pas contourné. |
| **Matériel de caisse** | Parc hétérogène : tablettes, postes tactiles, imprimantes ticket et scanners du marché local. Pas de matériel certifié imposé. | Le POS s'exécute dans le navigateur, sans pilote propriétaire. L'impression passe par les mécanismes standard du système, ce qui écarte le tiroir-caisse piloté et la balance connectée du périmètre Phase 1. |
| **Délai** | Cadence de sprints hebdomadaires, 29 sprints pour la Phase 1. | Chaque sprint doit produire un incrément démontrable ; aucun lot ne dépasse deux sprints sans livrable intermédiaire visible. |

### 4.1 Hypothèses ouvertes à lever

Conformément à la méthode retenue, aucune contrainte n'est inventée silencieusement. Les points ci-dessous sont des hypothèses de rédaction ; chacun a un sprint et un porteur de levée assignés.

| Réf. | Hypothèse posée | Levée prévue |
|---|---|---|
| **H1** | L'état réel du code (modèles, endpoints, écrans, modules déjà présents) correspond aux budgets déclarés : 180 modèles, 600 endpoints, 90 écrans. | Sprint 1 — inventaire automatique du dépôt, fichier INVENTAIRE_EXISTANT.md. |
| **H2** | Les taux CNaPS employeur (13 %) et OSTIE employeur (5 %) retenus correspondent à la pratique en vigueur ; des sources secondaires citent des valeurs plus anciennes divergentes. | Sprint 18 — validation écrite par l'expert-comptable OECFM. Ces taux ne servent qu'à amorcer la table, la paie étant en Phase 3. |
| **H3** | La loi malgache applicable à la protection des données personnelles est la loi n° 2014-038 ; ses obligations déclaratives exactes pour un éditeur SaaS restent à confirmer. | Sprint 21 — vérification juridique avant mise en production commerciale. |
| **H4** | Le matériel Hetzner retenu (16 Go de RAM, CPU seul) supporte gpt-oss:20b quantifié en Q4 à une latence acceptable pour un usage conversationnel. | Sprint 19 — banc d'essai réel ; déclenche le repli sur un modèle plus petit ou sur l'API cloud si la latence dépasse le seuil fixé. |
| **H5** | Les ratios d'estimation Jour-Homme / Jour-Token utilisés ne sont pas calibrés sur des mesures réelles de ce projet. | Sprints 1 à 4 — mesure réelle et recalibrage du reste du plan à l'issue du sprint 4. |

**Règle de gestion des hypothèses.** Une hypothèse non levée à la date prévue devient un risque actif et remonte en revue de sprint. Aucune hypothèse réglementaire (H2, H3) ne peut être « levée par défaut » au motif que le développement doit avancer : le paramètre reste marqué non validé en base et l'écran affiche cet état à l'utilisateur.

## 5. Architecture applicative

Les six couches, décision par décision

L'architecture cible est un monolithe modulaire Django, augmenté d'un unique service séparé pour l'IA. Ce n'est pas un choix par défaut : c'est la conséquence directe de la contrainte « développeur solo ». Un découpage en microservices multiplierait le coût opérationnel (déploiement, observabilité, cohérence transactionnelle) sans aucun bénéfice à l'échelle visée. Le seul service extrait est le gateway IA, pour trois raisons précises : isoler une charge CPU longue et imprévisible, permettre de le redémarrer ou de le désactiver sans toucher à l'ERP, et créer une frontière de sécurité nette entre le modèle de langage et la base de données.

****Vue d'ensemble des couches — Phase 1****

```
NAVIGATEUR (poste bureau / tablette)
    │  HTML + fragments HTMX · Alpine.js · Tailwind + tokens WideHalo
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  CADDY — TLS, compression brotli, en-têtes de sécurité               │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 1. PRÉSENTATION                                                │  │
│  │    shell · launchpad · data grid · formulaires · chatter       │  │
│  │    palette de commandes · états vides · composants cotton      │  │
│  │    moteur de vues configurables · filtres sauvegardés          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 2. LOGIQUE MÉTIER (Django 5.2 LTS, monolithe modulaire)        │  │
│  │    CRM · Sales · Accounting                                    │  │
│  │    moteurs transverses : workflow · recherche · permissions    │  │
│  │    notifications · audit                                       │  │
│  │    référentiel comptable abstrait (PCG 2005 | SYSCOHADA)       │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 3. DONNÉES                                                     │  │
│  │    PostgreSQL 15+ · RLS par tenant · rôle applicatif non-su    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│      ▲  API django-ninja — LECTURE SEULE, liste blanche              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 4. INTÉGRATION                                                 │  │
│  │    widehalo-ai-gateway (FastAPI) → Ollama local (CPU)          │  │
│  │                                  → repli Mistral (option)      │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
  5. INFRASTRUCTURE : Hetzner · Coolify · Docker Compose · Caddy
  6. TRANSVERSE : sécurité · gouvernance des données · i18n · observabilité
```

### 5.1 Couche présentation

**Type de client** : application web multi-pages rendue côté serveur, enrichie par échanges de fragments HTML (HTMX) et par un comportement local léger (Alpine.js). Pas de SPA, pas de duplication du modèle métier côté client. Un seul client pour la Phase 1 ; le responsive couvre le poste de bureau et la tablette. Deux exceptions assumées à la règle du rendu serveur : l'écran de caisse, qui embarque un cache local et une file de ventes pour fonctionner sans réseau, et le moteur de simulation, qui recalcule localement sur un modèle agrégé pour répondre sous 100 ms. Dans les deux cas, le serveur reste l'autorité : il réconcilie et il recalcule.

**Composition** : l'interface cesse d'être un ensemble de gabarits indépendants pour devenir un assemblage de composants réutilisables. Chaque composant est un fichier django-cotton appelé comme une balise HTML (<c-data-grid>), avec attributs et emplacements. C'est la condition pour qu'un développeur solo puisse produire 30 à 40 écrans cohérents sans les recoder un par un.

**Gestion d'état** : l'état de vérité reste sur le serveur. Alpine.js ne porte que l'état d'interface éphémère (ouverture d'un panneau, sélection en cours, brouillon local avant envoi). Ce partage strict évite le principal défaut des interfaces hybrides : deux sources de vérité qui divergent.

**Rendu et cache** : rendu serveur systématique ; fragments HTMX cacheables indépendamment ; ressources statiques versionnées avec cache navigateur long ; préchargement discret des écrans les plus probables depuis le launchpad.

**Design system** : à créer (voir section 7). Il n'existe pas de design system réutilisable dans l'existant. **[HYPOTHÈSE H1]**

### 5.2 Couche logique métier

**Découpage** : monolithe modulaire. Chaque module (CRM, Sales, Accounting) est une application Django autonome avec ses modèles, ses services et ses vues, communiquant avec les autres par des services explicites plutôt que par accès direct aux modèles. Cette discipline coûte peu aujourd'hui et préserve la possibilité d'extraire un module plus tard si le besoin apparaît réellement.

**Où vivent les règles métier** : dans une couche de services applicatifs, jamais dans les gabarits, jamais dans le JavaScript, jamais dupliquées dans des déclencheurs de base de données. Le calcul d'une TVA, la génération d'une écriture à partir d'une facture ou la transition d'un devis en commande sont des fonctions de service testables unitairement.

**Règles paramétrables** : tout ce qui peut changer par décision extérieure (loi de finances, décret, convention) est lu dans core_regulatory_parameter à la date de l'opération, jamais écrit dans le code. Le détail est en section 12.3.

**Traitements asynchrones** : la Phase 1 en a besoin pour quatre usages seulement — génération de PDF volumineux, imports de fichiers, envoi d'e-mails, appels au copilote IA, et construction du socle de simulation. La réception des ventes POS différées est en revanche traitée en synchrone, pour que la caisse sache immédiatement ce qui a été accepté et ce qui ne l'a pas été. Un ordonnanceur léger intégré à Django (tâches en base, sans courtier de messages supplémentaire) suffit à cette échelle et évite d'ajouter Redis et un service de workers au déploiement.

**Moteur de workflow générique.** Plutôt que de coder l'enchaînement d'états de chaque document (devis, commande, facture, opportunité) séparément, la Phase 1 introduit un moteur d'états déclaratif : états, transitions autorisées, conditions, effets de bord et permission requise. Chaque transition alimente automatiquement le chatter et le journal d'audit. C'est l'une des optimisations les plus rentables de la refonte : elle sera réutilisée telle quelle par les ordres de fabrication et les contrôles qualité en Phase 3.

### 5.3 Couche données et persistance

**Stockage** : PostgreSQL 15 ou supérieur, relationnel, en base unique. Les données d'un ERP sont fortement relationnelles et transactionnelles ; aucun besoin ne justifie un second moteur en Phase 1. La recherche plein texte s'appuie sur les capacités natives de PostgreSQL plutôt que sur un moteur d'indexation séparé.

**Multi-tenance** : isolation par discriminant tenant_id combinée à la Row Level Security de PostgreSQL. Le discriminant seul est fragile : un .filter() oublié dans une seule requête suffit à faire fuir les données d'un client vers un autre. La RLS transforme cet oubli en résultat vide plutôt qu'en incident. Le schéma par tenant a été écarté : il multiplie les migrations par le nombre de clients, ce qui est ingérable en solo.

**Migrations de schéma** : migrations Django versionnées, jouées automatiquement au déploiement, avec obligation de réversibilité pour toute migration touchant à des données comptables. Les migrations destructives sont interdites sur les exercices clos.

**Intégrité** : contraintes en base (clés étrangères, unicité, contraintes de vérification) plutôt que validation applicative seule, en particulier sur la numérotation des pièces comptables et l'équilibre débit/crédit des écritures.

### 5.4 Couche intégration

**API interne** : django-ninja, avec deux familles d'endpoints nettement séparées par convention de nommage. Les endpoints fragment renvoient du HTML à destination de HTMX ; les endpoints API renvoient du JSON typé par schémas Pydantic. Mélanger les deux produit des endpoints ambigus et une documentation OpenAPI inutilisable.

**API externe** : exposée sous /api/v1/, documentée automatiquement en OpenAPI, authentifiée par jeton par tenant. Elle reste volontairement étroite en Phase 1 : lecture des tiers, des documents de vente et des états comptables.

**Sous-ensemble IA** : la liste blanche d'endpoints en lecture seule consommable par le gateway est un sous-ensemble explicite de l'API, marqué comme tel dans le code et vérifié par un test d'intégration continue. Un endpoint n'entre dans cette liste que par décision explicite.

### 5.5 Couche infrastructure et déploiement

| Conteneur | Rôle | Dimensionnement Phase 1 |
|---|---|---|
| **caddy** | Terminaison TLS, compression, en-têtes de sécurité, service des fichiers statiques | Ressources marginales |
| **widehalo-web** | Application Django (gunicorn/uvicorn) | CX43 — dimensionnant pour la charge utilisateur |
| **widehalo-worker** | Tâches asynchrones et planifiées (PDF, imports, e-mails, construction du socle de simulation) | 1 processus, même image que le web |
| **postgres** | Base de données unique, RLS activée | Volume persistant + sauvegardes chiffrées |
| **widehalo-ai-gateway** | Microservice FastAPI, function-calling | Faible empreinte, redémarrable seul |
| **ollama** | Modèle de langage local, CPU uniquement | ~13 Go de modèle, 16 Go de RAM — poste le plus contraint [H4] |

**Environnements** : développement local, pré-production sur CX33, production sur CX43. La pré-production sert aussi de banc de mesure de performance en réseau dégradé et d'environnement de démonstration client.

**Déploiement** : intégration continue → construction d'image → déploiement Coolify. Aucun déploiement manuel en production. Les migrations et la collecte des fichiers statiques font partie du pipeline, jamais d'une intervention humaine.

**Observabilité** : journaux structurés corrélés par identifiant de requête et par tenant, métriques de temps de réponse par endpoint, taux d'erreur, sondes de santé Coolify, et surveillance spécifique de la mémoire du conteneur Ollama — c'est le composant qui dégradera l'ensemble du serveur s'il n'est pas borné.

### 5.6 Couche transverse

Deux thèmes traversent toutes les couches précédentes et ne doivent pas être traités comme des sous-parties de l'infrastructure : la sécurité (section 6) et la gouvernance des données (section 8). S'y ajoutent l'internationalisation, traitée en section 7.6, et l'observabilité décrite ci-dessus. Le journal d'audit est le point de rencontre des deux : il relève de la sécurité par sa fonction de preuve, et de la gouvernance par sa rétention.

## 6. Sécurité

Niveau d'exigence proportionné à des données comptables de tiers

Le niveau d'exigence n'est pas celui d'un site vitrine ni celui d'un établissement bancaire. WideHalo héberge la comptabilité, le fichier client et les marges de PME tierces : une fuite inter-tenant ou une altération non tracée d'écriture détruirait la crédibilité commerciale du produit, même sans conséquence légale immédiate. Les trois priorités sont donc, dans l'ordre : l'isolation entre clients, la traçabilité des écritures, et le confinement du copilote IA.

### 6.1 Authentification

- Authentification par identifiant et mot de passe, avec politique de complexité et hachage fort (paramétrage Django par défaut, non affaibli).
- Second facteur (TOTP) obligatoire pour les rôles Comptable et Administrateur, optionnel pour les autres. Un accès comptable sans second facteur est une exposition disproportionnée au risque d'hameçonnage.
- Sessions expirant après inactivité, invalidation de toutes les sessions au changement de mot de passe, limitation du nombre de tentatives par compte et par adresse.
- Pas de délégation d'identité externe (SSO) en Phase 1 : aucun besoin client identifié, et la surface d'attaque ajoutée serait supérieure au bénéfice.

### 6.2 Autorisation

Modèle RBAC par rôle métier, inspiré de la logique de rôles de SAP Fiori : le rôle détermine à la fois ce que l'utilisateur peut faire et ce qu'il voit. Un commercial n'a pas une version grisée du menu comptable, il n'a pas de menu comptable. Trois niveaux d'autorisation se cumulent :

| Niveau | Portée | Mise en œuvre |
|---|---|---|
| **Tenant** | L'utilisateur ne voit que les données de son entreprise. | RLS PostgreSQL + variable de session injectée par middleware. Garde-fou de dernière ligne. |
| **Rôle** | Accès aux modules, aux écrans et aux actions (lire, créer, valider, annuler). | Matrice rôle × action évaluée côté serveur, y compris sur les endpoints de fragments HTMX — masquer un bouton n'est pas une autorisation. |
| **Objet** | Restrictions fines : un commercial ne voit que son portefeuille, un exercice clos n'est plus modifiable. | Règles applicatives dans la couche de services, testées unitairement. |

**Règle non négociable sur la RLS.** Le rôle PostgreSQL utilisé par l'application ne doit jamais être superutilisateur : un superutilisateur contourne silencieusement toutes les politiques de Row Level Security, ce qui annule complètement l'isolation multi-tenant tout en donnant l'illusion qu'elle fonctionne. Un test d'intégration continue vérifie à chaque déploiement que le rôle applicatif n'a ni SUPERUSER ni BYPASSRLS, et qu'une requête sans tenant positionné renvoie zéro ligne.

### 6.3 Chiffrement et secrets

- **En transit** : TLS obligatoire de bout en bout, HSTS activé, redirection HTTP → HTTPS au niveau de Caddy. Le trafic entre conteneurs reste sur le réseau interne Docker.
- **Au repos** : chiffrement du volume de données et chiffrement des archives de sauvegarde avant transfert hors du serveur. Une sauvegarde non chiffrée stockée ailleurs est le maillon faible classique de ce type d'architecture.
- **Secrets** : variables d'environnement gérées par Coolify, jamais dans le dépôt, rotation documentée des jetons d'API et de la clé applicative Django. Un test de CI échoue si un secret est détecté dans le code source.

### 6.4 Sécurité applicative

Le rendu serveur élimine par construction une partie des risques classiques d'interface riche, mais en introduit d'autres, propres à HTMX. Les points de vigilance retenus :

| Risque | Spécificité WideHalo | Contre-mesure |
|---|---|---|
| **Contrôle d'accès défaillant** | Les endpoints de fragments HTMX sont nombreux et faciles à oublier dans la matrice de permissions. | Décoration obligatoire de tout endpoint ; test de CI listant les endpoints sans déclarations de permission et faisant échouer la construction. |
| **Injection de contenu (XSS)** | Les fragments HTML renvoyés par HTMX sont insérés directement dans le DOM ; du contenu utilisateur mal échappé s'exécute. | Échappement automatique des gabarits jamais désactivé ; politique de sécurité de contenu (CSP) stricte ; revue spécifique de tout usage de contenu brut. |
| **Falsification de requête (CSRF)** | Toutes les actions passent par des requêtes HTMX, pas par des formulaires classiques. | Jeton CSRF injecté globalement dans les en-têtes HTMX ; vérification côté serveur sur toute méthode non idempotente. |
| **Injection SQL** | Risque faible via l'ORM, mais réel sur les requêtes de rapport construites dynamiquement. | Requêtes paramétrées exclusivement ; interdiction absolue de construire du SQL par concaténation, y compris dans le moteur de rapports. |
| **Injection de prompt** | Le copilote lit des données saisies par des tiers (nom de société, commentaire, libellé d'écriture) susceptibles de contenir des instructions. | Le modèle ne dispose que d'outils en lecture seule ; aucune action d'écriture n'est atteignable même si le modèle est détourné. Voir section 13.4. |
| **Épuisement de ressources** | Une requête au copilote mobilise le CPU pendant plusieurs secondes ; quelques requêtes simultanées peuvent dégrader tout le serveur. | File d'attente avec profondeur bornée, quota par utilisateur et par heure, délai maximal, dégradation explicite plutôt que blocage. |

### 6.5 Audit et traçabilité

Le journal d'audit n'est pas un confort : c'est la condition pour qu'un expert-comptable accepte le système. Sont journalisés de manière non modifiable par l'utilisateur : toute création, modification ou annulation d'écriture comptable et de document de vente validé ; toute transition d'état ; toute modification d'un paramètre réglementaire ; toute connexion et tout échec d'authentification ; tout appel d'outil par le copilote IA. Chaque entrée conserve l'auteur, l'horodatage, l'objet, l'écart avant/après et l'adresse d'origine.

Les documents comptables validés ne sont jamais modifiés ni supprimés : ils sont annulés par contre-passation ou par avoir, ce qui est à la fois une exigence comptable et une propriété de sécurité.

## 7. UX/UI et confort d'usage

Le cœur de la refonte — 70 % de l'effort

Cette section est le centre de gravité du document. Elle ne décrit pas des écrans (voir section 13) mais le système qui permettra de les produire de façon cohérente et rapide, et les principes vérifiables auxquels ils devront répondre.

### 7.1 Ce que l'on emprunte, et ce que l'on refuse

| Référence | Ce que l'on reprend | Ce que l'on écarte, et pourquoi |
|---|---|---|
| **HubSpot** | La clarté avant la densité : une action principale évidente par écran. Les états vides pédagogiques qui expliquent la valeur et proposent l'action. L'onboarding progressif. La recherche globale. Les notifications porteuses d'action. | L'orientation « marketing » de la densité : un comptable a besoin de voir 40 lignes à l'écran, pas 8 cartes aérées. La densité devient un réglage, pas un dogme. |
| **Odoo** | La bascule entre plusieurs vues sur la même donnée (liste, kanban, formulaire, tableau croisé, calendrier). Le fil d'Ariane. Les filtres et regroupements sauvegardables. La création rapide en ligne. Le chatter avec messages, notes internes et activités. | Le modèle de personnalisation par héritage de vues XML : trop puissant, trop coûteux à maintenir en solo. WideHalo se limite à un moteur de vues déclaratif fermé. |
| **SAP Fiori / Easy Access** | Le point d'entrée par rôle : un launchpad de tuiles filtrées par le métier de l'utilisateur, avec tuiles à compteur, favoris épinglés et documents récents. La page objet structurée (en-tête d'identité et de statut, onglets, actions contextuelles). | L'arbre de transactions à codes de SAP Easy Access, conçu pour des utilisateurs experts formés. Et la mécanique de catalogues et d'espaces de Fiori, surdimensionnée pour une PME de 20 personnes. |

### 7.2 Sept principes vérifiables

Un principe UX non vérifiable est un slogan. Chacun des sept principes ci-dessous est assorti d'un critère contrôlable en recette.

| Principe | Énoncé | Critère de vérification |
|---|---|---|
| **P1 — Une action principale** | Chaque écran a une action principale visuellement dominante et unique. | Revue d'écran : un seul bouton de style primary visible sans défilement. |
| **P2 — Cohérence par composition** | Aucun écran n'introduit de style local : tout provient de la bibliothèque. | Test de CI : aucune couleur ni espacement en dur hors du fichier de tokens. |
| **P3 — Réaction immédiate** | Toute interaction produit un retour visuel en moins de 100 ms, même si la réponse serveur est plus lente. | Indicateur de chargement présent sur 100 % des actions HTMX ; vérifié en réseau bridé. |
| **P4 — Rien ne se perd** | Une saisie interrompue (réseau, électricité, fermeture accidentelle) est récupérable. | Test : couper le réseau au milieu d'un devis, recharger, retrouver le brouillon. |
| **P5 — L'erreur est un écran** | États vides, erreurs et chargements sont conçus explicitement, jamais laissés au hasard. | Chaque écran livré fournit ses quatre états : plein, vide, en chargement, en erreur. |
| **P6 — Le clavier suffit** | Les parcours à fort volume (saisie de lignes, saisie d'écriture) sont réalisables sans souris. | UC3 et UC4 exécutables entièrement au clavier, chronométrés. |
| **P7 — Accessible et tactile** | Contraste conforme WCAG AA, navigation clavier complète, cibles tactiles ≥ 44 px. | Audit automatisé de contraste et de rôles ARIA intégré à la CI. |

### 7.3 Architecture d'information et navigation

****Structure de navigation cible****

```
BARRE SUPÉRIEURE (persistante, toutes pages)
[logo] [⊙ apps] [⌕ Rechercher…  Ctrl+K] [✦ copilote] [activités] [○ notif] [avatar]
LAUNCHPAD (page d'accueil, contenu filtré par rôle)
┌─ Mes favoris ───────────────────────────────────────────────────┐
│  [Nouveau devis]  [Pipeline]  [Saisie d'écriture]  [Balance]    │
└─────────────────────────────────────────────────────────────────┘
┌─ À traiter ─────────────────────────────────────────────────────┐
│  ┃ 7 ┃ devis à relancer   ┃ 12 ┃ factures échues  ┃ 3 ┃ à lettrer│
└─────────────────────────────────────────────────────────────────┘
┌─ Documents récents ─────────────────────────────────────────────┐
└─────────────────────────────────────────────────────────────────┘
APPLICATION OUVERTE
Ventes › Devis › DEV-2026-0148          ← fil d'Ariane cliquable
[ Liste | Kanban | Tableau croisé | Calendrier ]  [Filtres ▾] [Grouper ▾]
┌─ PAGE OBJET ───────────────────────────────┐┌─ CHATTER ─────────┐
│  en-tête : client, montant, statut, actions ││  messages         │
│  onglets : Lignes | Conditions | Documents  ││  notes internes   │
│                                             ││  activités à venir│
└─────────────────────────────────────────────┘└───────────────────┘
```

Le sélecteur d'applications de la Phase 1 présente Ventes, Comptabilité, Rapports et Paramètres. Les emplacements des applications des phases 2 et 3 sont prévus dans la structure mais non affichés : un sélecteur rempli de modules grisés « à venir » est une source de frustration, pas une promesse commerciale.

### 7.4 Design system

| Élément | Décision Phase 1 |
|---|---|
| **Grille** | 12 colonnes, gouttière 16 px, largeur de contenu maximale 1440 px. Les écrans de saisie dense (grilles, écritures) exploitent toute la largeur disponible. |
| **Densité** | Deux modes commutables par l'utilisateur : confortable (par défaut, usage occasionnel) et compact (comptable, ADV). Le choix est mémorisé par utilisateur. |
| **Typographie** | Une seule famille sans empattement, échelle fermée à 6 tailles (12 / 14 / 16 / 20 / 24 / 32). Chiffres à chasse fixe obligatoires dans toutes les colonnes de montants : sans cela, une colonne de montants est illisible. |
| **Couleur** | Une couleur de marque, une couleur d'accent, quatre couleurs sémantiques (succès, alerte, danger, information), une échelle de gris à 9 niveaux. La couleur ne porte jamais seule une information : tout statut combine couleur, libellé et, si besoin, icône. |
| **Tokens** | Couleurs, espacements (base 4 px), rayons, ombres, hauteurs de plan, durées d'animation, définis une seule fois en variables CSS et consommés par la configuration Tailwind. Aucune valeur en dur ailleurs (principe P2). |
| **Icônes** | Un seul jeu d'icônes vectorielles, importables individuellement pour ne pas charger une police complète. |
| **Thème sombre** | Livré en Phase 1 car il découle des tokens sans coût supplémentaire significatif, et parce qu'il réduit la fatigue sur les postes de saisie prolongée. |
| **États** | Sept états définis pour chaque composant interactif : normal, survol, focus (anneau visible obligatoire), pressé, désactivé, chargement, erreur. |

### 7.5 Bibliothèque de composants à construire

La bibliothèque est construite dans les sprints 2 à 8, avant tout écran métier. C'est la décision d'ordonnancement la plus importante du plan : construire les écrans avant les composants garantit de les reconstruire deux fois.

| Composant | Spécification | Sprint |
|---|---|---|
| **c-data-grid** | Grille universelle : colonnes configurables et mémorisables, tri, pagination serveur, sélection multiple, actions de masse, colonnes figées, densité, export. Toutes les listes de l'ERP en découlent. | 5 |
| **c-view-switcher** | Bascule liste / kanban / tableau croisé / calendrier sur le même jeu de données et le même filtre courant. | 6 |
| **c-filter-bar** | Filtres combinables, regroupements, recherche locale, sauvegarde de vue personnelle ou partagée. | 6 |
| **c-form / c-field** | Formulaire long à onglets, validation en ligne champ par champ, sauvegarde de brouillon, navigation clavier complète, messages d'erreur au niveau du champ. | 7 |
| **c-line-editor** | Saisie de lignes de document (devis, facture, écriture) : ajout au clavier, duplication, réordonnancement, totaux recalculés côté serveur. | 7 |
| **c-chatter** | Fil unifié : messages, notes internes, activités planifiées, abonnés, historique des transitions d'état. | 8 |
| **c-search-palette** | Palette de commandes Ctrl/Cmd+K : recherche d'enregistrements, d'actions et de navigation, résultats groupés par type. | 4 |
| **c-tile** | Tuile de launchpad : statique, à compteur ou à indicateur, actualisée sans rechargement de page. | 3 |
| **c-empty-state** | État vide pédagogique : ce que contient normalement cet écran, pourquoi c'est utile, action pour démarrer, lien vers l'import. | 2 |
| **Secondaires** | c-button, c-breadcrumb, c-tabs, c-modal, c-drawer, c-toast, c-skeleton, c-badge, c-stat-card, c-avatar, c-money. | 2–3 |

### 7.6 Performance perçue et réseau dégradé

C'est une exigence de conception, pas un réglage de fin de projet. Un ERP qui met huit secondes à afficher une liste est abandonné quelle que soit sa richesse fonctionnelle.

- **Budget de charge initiale** : le chemin critique (HTML + CSS + JavaScript nécessaire au premier rendu utile) est plafonné et vérifié en intégration continue. Ce plafond est la raison principale du refus d'une architecture SPA, dont les paquets se comptent en centaines de kilo-octets.
- **Pagination serveur systématique** : aucune liste ne charge intégralement son jeu de données, y compris à l'export (traitement asynchrone avec téléchargement différé).
- **Endpoints agrégés** : sur une liaison à forte latence, ce sont les allers-retours qui coûtent, pas les octets. Le launchpad charge ses tuiles en un appel groupé, pas un appel par tuile.
- **Compression et images** : brotli au niveau de Caddy ; images en format moderne, dimensionnées à l'usage, chargées paresseusement.
- **Amélioration progressive** : les parcours essentiels restent fonctionnels si le JavaScript échoue à se charger — dégradés, mais utilisables.
- **Mode dégradé explicite** : lorsque la connexion est perdue, l'interface le dit, conserve la saisie en cours et annonce clairement ce qui sera envoyé au retour du réseau. Le silence est pire que la panne.
- **Hors ligne d'abord pour la caisse** : le POS ne se contente pas d'un mode dégradé, il est conçu pour fonctionner sans réseau par défaut — catalogue, tarifs et session en cache local, ventes en file, synchronisation ensuite. Le nombre de ventes en attente est affiché en permanence à l'écran de caisse : le caissier doit savoir où il en est sans avoir à le demander.
- **Budget de charge du socle de simulation** : le modèle agrégé chargé pour l'atelier de scénarios est plafonné et vérifié en CI, au même titre que le chemin critique. C'est ce qui rend le « temps réel » tenable sur une liaison lente.

### 7.7 Internationalisation

Le français est la seule langue livrée en Phase 1, mais l'infrastructure d'internationalisation est mise en place dès le sprint 2 : chaînes externalisées sans exception, formats de date, de nombre et de devise centralisés, et pas de concaténation de phrases. Reprendre une interface pour l'internationaliser après coup coûte plusieurs fois le prix de le faire dès le début. Le montant en Ariary suit une règle unique de présentation (séparateur de milliers, absence de décimale sauf besoin explicite, alignement à droite, chasse fixe), implémentée une fois dans c-money.

## 8. Gouvernance des données

Cycle de vie, classification, conformité, sauvegarde

### 8.1 Classification

| Classe | Exemples en Phase 1 | Règles associées |
|---|---|---|
| **Sensible** | Écritures comptables, marges, rémunérations, coordonnées bancaires, données d'identification des contacts. | Chiffrement au repos et en transit ; accès restreint par rôle ; toute consultation d'un export complet est journalisée ; jamais transmise à un service tiers sans décision explicite du client. |
| **Interne** | Pipeline commercial, catalogue et tarifs, historique des documents, notes internes. | Accès par rôle ; export autorisé aux rôles habilités ; journalisé en cas d'export de masse. |
| **Opérationnelle** | Préférences d'affichage, vues sauvegardées, journaux techniques. | Rétention courte ; purge automatique ; aucune valeur probante. |
| **Référentielle publique** | Plan de comptes PCG 2005, taux légaux, unités de mesure. | Versionnée, jamais supprimée (l'historique conditionne le recalcul d'exercices antérieurs). |

### 8.2 Cycle de vie et rétention

La règle structurante est que la donnée comptable ne se supprime pas. Elle est annulée, contre-passée ou archivée, jamais effacée, y compris à la demande de l'utilisateur — ce qui crée une tension avec un éventuel droit à l'effacement, tranchée en faveur de l'obligation de conservation comptable, laquelle prévaut sur ce type de demande.

| Donnée | Conservation active | Archivage | Suppression |
|---|---|---|---|
| **Documents comptables et de vente validés** | Exercice courant + 2 ans en ligne | Au-delà, archive froide exportée et chiffrée | Jamais dans la période légale de conservation |
| **Contacts et sociétés** | Tant que la relation est active | 3 ans après le dernier contact | Sur demande, si aucune pièce comptable ne les référence |
| **Pistes et opportunités perdues** | 12 mois | Anonymisation après 24 mois | Automatique |
| **Journal d'audit** | 24 mois en ligne | Export mensuel chiffré | Jamais avant la fin de la rétention |
| **Journaux techniques** | 30 jours | — | Purge automatique |
| **Historique des échanges avec le copilote IA** | 90 jours | — | Purge automatique ; suppression immédiate possible par l'utilisateur |

### 8.3 Conformité

- **Localisation** : les données sont hébergées sur des serveurs Hetzner situés en Europe, donc hors du territoire malgache. Ce point doit être écrit dans le contrat client et non découvert après coup ; il est également un argument commercial ambivalent (fiabilité perçue contre souveraineté) qu'il vaut mieux traiter frontalement.
- **Loi malgache sur la protection des données personnelles** : les obligations exactes applicables à un éditeur SaaS restent à confirmer juridiquement **[HYPOTHÈSE H3]**. Le produit est conçu pour les satisfaire par construction : minimisation des données collectées, finalité explicite, journal des accès, capacité d'extraction et de rectification.
- **RGPD** : non applicable à un client purement malgache, mais applicable dès qu'un client traite des données de personnes situées dans l'Union européenne — cas réel pour un exportateur textile. Le produit fournit les mécanismes nécessaires (extraction, rectification, registre des accès) sans prétendre à une certification.
- **Obligations comptables** : conservation des pièces, numérotation continue et non modifiable, traçabilité des corrections. Ces exigences sont implémentées comme des contraintes techniques, pas comme des recommandations d'usage.

### 8.4 Qualité des données

Trois mécanismes en Phase 1 : détection des doublons à la création d'une société ou d'un contact (rapprochement sur le nom et l'identifiant fiscal, avec proposition de fusion) ; contrôles de cohérence bloquants à la validation d'un document (équilibre d'une écriture, compte de TVA cohérent avec le taux, date dans un exercice ouvert) ; et rapport de qualité mensuel signalant les enregistrements incomplets.

### 8.5 Sauvegarde et reprise

| Paramètre | Cible Phase 1 | Moyen |
|---|---|---|
| **RPO — perte de données maximale tolérée** | 24 heures | Sauvegarde complète quotidienne chiffrée, transférée hors du serveur de production. |
| **RTO — délai de remise en service** | 4 heures | Procédure de restauration écrite et testée ; image applicative reconstruite depuis le dépôt. |
| **Vérification** | Mensuelle, obligatoire | Restauration réelle sur l'environnement de pré-production, avec contrôle d'un jeu de données témoin. Une sauvegarde jamais restaurée n'est pas une sauvegarde. |
| **Conservation** | 30 sauvegardes quotidiennes + 12 mensuelles | Stockage objet chiffré, distinct du serveur applicatif. |

**Spécificité Hetzner à intégrer au calcul de coût.** Un serveur Hetzner reste facturé même éteint : suspendre une machine ne réduit pas la facture. La seule réduction réelle pendant une période d'inactivité passe par un instantané suivi de la suppression du serveur. Ce point concerne surtout l'environnement de pré-production, qui n'a pas vocation à tourner en continu.

## 9. Interopérabilité et outils tiers

Peu d'intégrations, mais chacune sous contrôle

La Phase 1 limite volontairement les dépendances externes. Chaque intégration ajoutée est une source de panne que le développeur solo devra diagnostiquer un dimanche soir. Le critère d'admission est simple : l'intégration est-elle indispensable à un parcours de Phase 1, et l'application reste-t-elle utilisable si le tiers tombe ?

| Intégration | Usage | Mode | Comportement en cas de panne du tiers |
|---|---|---|---|
| **Serveur d'envoi d'e-mail (SMTP)** | Envoi des devis et factures, notifications, réinitialisation de mot de passe. | SMTP sortant, file d'attente asynchrone | Le document reste généré et téléchargeable ; l'envoi est mis en file et rejoué. L'utilisateur voit l'état réel de l'envoi, jamais un faux succès. |
| **Ollama (modèle local)** | Copilote IA — backend par défaut. | HTTP sur le réseau interne Docker | Le copilote s'annonce indisponible ; l'ERP fonctionne intégralement sans lui. L'IA est un confort, jamais un chemin critique. |
| **API Mistral (repli)** | Copilote IA — repli optionnel activable par tenant. | HTTPS sortant, clé par installation | Retour au modèle local, ou indisponibilité annoncée. Aucune donnée n'est envoyée à un tiers sans activation explicite et information du client. |
| **Stockage objet de sauvegarde** | Dépôt des archives chiffrées hors du serveur. | Protocole S3, tâche planifiée | Alerte immédiate ; conservation locale temporaire. Un échec de sauvegarde silencieux est traité comme un incident majeur. |
| **API publique WideHalo** | Consommation par des tiers côté client (rare en Phase 1). | REST, OpenAPI, jeton par tenant | Sans objet — WideHalo est ici le fournisseur. Limitation de débit par jeton. |

### 9.1 Gouvernance des échanges

- **Propriété des données** : les données restent celles du client. Aucun flux sortant vers un tiers n'est activé par défaut. L'activation du repli cloud pour l'IA est une décision explicite, journalisée, et l'écran de configuration indique en clair quelles données sortiraient du serveur.
- **Résilience** : tout appel sortant est borné par un délai maximal, réessayé avec espacement croissant, et protégé par un disjoncteur qui coupe les appels après une série d'échecs plutôt que de saturer les workers.
- **Substituabilité** : les deux backends d'IA sont interchangeables derrière une interface unique du gateway. Le coût de changement de fournisseur doit rester faible ; c'est la raison d'être du gateway autant que la sécurité.
- **Préparation Phase 2** : le canal de notification est abstrait dès la Phase 1 (destinataire, gabarit, canal, statut d'envoi, réessai). WhatsApp deviendra un adaptateur supplémentaire et non une refonte du modèle de notification.

## 10. Scalabilité

Cinq dimensions, dont la plus contraignante n'est pas le trafic

Pour WideHalo, la dimension critique n'est ni la charge ni le volume : c'est la capacité de l'équipe, réduite à une personne. Un ERP peut absorber dix fois plus de clients sans changer d'architecture, mais pas dix fois plus de complexité fonctionnelle sans changer de méthode.

| Dimension | Situation Phase 1 | Seuil où elle devient un problème | Option prévue |
|---|---|---|---|
| **Charge / trafic** | Quelques dizaines d'utilisateurs simultanés par tenant, pointes en fin de mois (clôture, facturation) et en fin de journée (clôtures de caisse simultanées sur plusieurs points de vente). | Saturation CPU du CX43 aux pointes de clôture, ou latence supérieure à 1 s sur les listes. | Augmentation verticale du serveur (immédiate, sans changement d'architecture), puis séparation du processus web et du worker sur deux machines. |
| **Volume de données** | Quelques centaines de milliers de lignes d'écriture et de documents par tenant et par an ; le POS ajoute un volume de tickets nettement supérieur en nombre mais faible en taille. | Dégradation des états comptables cumulés et des listes filtrées au-delà de 3 à 5 exercices en ligne. | Index ciblés dès la Phase 1 ; partitionnement des écritures par exercice et archivage des exercices anciens si le seuil est atteint. |
| **Équipe de développement** | Un développeur solo assisté par IA. Dimension la plus contraignante. | Dès que la surface fonctionnelle dépasse ce qu'une personne peut tenir en tête et corriger — seuil déjà proche. | Budgets d'architecture vérifiés en CI, moteurs génériques plutôt que code spécifique répété, bibliothèque de composants, suppression forcée des écrans legacy. |
| **Géographique / multi-tenant** | Tous les tenants sur une base unique, isolation par RLS. Un seul pays. | Au-delà de quelques dizaines de tenants actifs, ou à l'arrivée d'un pays au référentiel comptable différent. | L'abstraction du référentiel comptable livrée en Phase 1 rend l'ajout d'un pays paramétrable. Un tenant très volumineux peut être isolé sur sa propre instance sans changer le code. |
| **Coût** | Deux serveurs, un stockage de sauvegarde, un modèle local sans coût d'API. | Le modèle local devient le premier poste de consommation mémoire ; le repli cloud créerait un coût variable par usage. | Quota d'appels IA par tenant, modèle plus petit si nécessaire, pré-production éteinte par instantané plutôt que maintenue. |

### 10.1 Budgets d'architecture révisés

Les budgets existants sont un excellent garde-fou et doivent être conservés, mais la Phase 1 ajoute légitimement des entités transverses (vues, filtres, préférences, chatter, notifications, workflow, audit, paramètres réglementaires, référentiel comptable) et fait coexister temporairement deux interfaces. Les rehausser est un choix explicite, préférable à leur contournement silencieux.

| Budget | Actuel | Révisé Phase 1 | Justification |
|---|---|---|---|
| **Modèles** | 180 | 230 | ~15 à 18 modèles transverses (chatter, notifications, vues, audit, paramètres, référentiel comptable), ~10 pour le POS (point de vente, caisse, session, ticket, ligne, règlement, mouvement d'espèces, écart, file de synchronisation) et ~4 pour la simulation (socle, scénario, levier, comparaison). |
| **Endpoints** | 600 | 720 | Fragments HTMX, outils IA en lecture seule, API de synchronisation du POS et endpoints de socle et de recalcul de la simulation. |
| **Écrans (total)** | 90 | 135 | Coexistence temporaire ancienne / nouvelle interface, plus les écrans de caisse, de back-office POS et de simulation. |
| **Écrans legacy** | — | budget décroissant | Nouveau budget dédié, réduit à chaque sprint de migration. C'est le mécanisme qui force l'étape de suppression et évite de conserver deux systèmes indéfiniment. |

**Le budget décroissant d'écrans legacy est la mesure la plus importante de cette section.** Sans lui, une migration écran par écran ne produit pas un système refondu mais deux systèmes à maintenir en parallèle, ce qui est le pire des résultats possibles pour un développeur seul. Le test de CI échoue si le nombre d'écrans legacy dépasse la valeur cible du sprint en cours.

## 11. Choix technologiques

Comparatifs et compromis assumés

La stack backend est imposée par l'existant et n'est pas rouverte. En revanche, la couche présentation étant l'objet de la refonte, le choix y est réexaminé formellement plutôt qu'hérité par défaut. La grille de comparaison retenue est identique pour tous les candidats : adéquation au contexte, coût d'apprentissage pour un développeur seul, maturité, écosystème, coût total de possession et licence.

### 11.1 Architecture de la couche présentation

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Composants serveur + HTMX + Alpine django-cotton** | Continuité avec l'existant, aucune duplication du modèle métier, charge initiale très faible (adaptée au réseau cible), composition par balises lisibles, chaîne de construction légère. | Les interactions très riches (glisser-déposer complexe, édition hors ligne poussée) demandent du code spécifique. | **Retenu** |
| **Composants serveur alternatifs django-components, JinjaX** | Plus grande puissance d'expression, proche des conventions de composants modernes. | Syntaxe moins proche du HTML, courbe d'apprentissage supérieure, moins immédiat pour un gabarit Django existant. | Complément ponctuel |
| **Framework à état serveur type Tetra** | Encapsulation complète Python + HTML + JS, état conservé côté serveur. | Écosystème jeune, dépendance structurante à un projet de petite taille — risque disproportionné pour un socle destiné à durer. | Écarté |
| **SPA + API JSON React ou Vue + django-ninja** | Interactions les plus riches, écosystème de composants très fourni, compétence largement disponible sur le marché. | Réécriture complète de la présentation, duplication de la logique de validation, paquets lourds contraires à l'objectif O4, doublement de la charge de maintenance pour une seule personne. | Écarté |

Le compromis assumé est clair : WideHalo renonce à quelques interactions haut de gamme (que HubSpot ou Odoo se permettent grâce à des équipes front dédiées) en échange d'une interface légère, maintenable par une personne, et rapide sur le réseau réel des clients. Ce compromis est le bon pour ce produit ; il devrait être réexaminé si l'équipe atteignait trois développeurs ou plus. Les deux écrans qui s'en écartent — la caisse et l'atelier de scénarios — embarquent délibérément plus de logique locale, parce que leur exigence (encaisser sans réseau, répondre sous 100 ms) ne peut pas être satisfaite par un aller-retour serveur. Cette exception est bornée à ces deux écrans et documentée comme telle, pour qu'elle ne se propage pas au reste de l'application.

### 11.2 Bibliothèque de composants visuels

| Candidat | Licence | Apport | Décision |
|---|---|---|---|
| **Tailwind CSS** | Open source | Base utilitaire et système de tokens. Socle de tout le design system. | **Retenu** |
| **DaisyUI** | MIT, gratuit en usage commercial | Classes sémantiques prêtes à l'emploi et gestion native des thèmes (dont le thème sombre), ce qui évite d'écrire la base du design system à la main. | **Retenu comme base** |
| **Flowbite** | Noyau MIT | Composants interactifs plus avancés là où DaisyUI s'arrête. | Complément ponctuel |
| **Bibliothèque commerciale (type Tailwind Plus)** | Payante | Qualité visuelle supérieure immédiate. | Écarté — coût non justifié en Phase 1 |

**Limite à budgéter explicitement.** Ni DaisyUI ni Flowbite ne garantissent une accessibilité complète : les rôles ARIA, la gestion du focus dans les fenêtres modales et la navigation clavier des composants complexes restent à la charge du développeur. Un budget d'accessibilité explicite est provisionné (sprint 21) plutôt que supposé couvert par la bibliothèque.

### 11.3 Composants confirmés sans réexamen

| Brique | Choix | Motif de confirmation |
|---|---|---|
| **Framework applicatif** | Django 5.2 LTS | Support long terme aligné sur l'horizon du produit ; existant ; écosystème complet (ORM, migrations, i18n, admin, sécurité). |
| **Couche API** | django-ninja | Typage Pydantic et OpenAPI automatique, indispensables pour décrire les outils IA de façon fiable. |
| **Base de données** | PostgreSQL 15+ | RLS (exigée par le multi-tenant), recherche plein texte intégrée, robustesse transactionnelle. |
| **Service IA** | FastAPI | Adapté à un service réseau asynchrone à faible empreinte ; sépare nettement le cycle de vie de l'IA de celui de l'ERP. |
| **Modèle de langage** | Ollama local, repli API cloud | Coût marginal nul et confidentialité par défaut ; le repli couvre les cas où la latence locale serait inacceptable. |
| **Production de PDF** | Bibliothèque Python déjà utilisée sur le projet | Documents commerciaux et états comptables ; génération asynchrone pour les volumes importants. |
| **Hébergement** | Hetzner + Coolify + Docker Compose + Caddy | Rapport coût/puissance adapté à la contrainte budgétaire ; déploiement maîtrisable sans compétence DevOps dédiée. |

## 12. Socle transverse et référentiel comptable

Les 30 % d'optimisations qui rendent les 70 % d'UX possibles

Cette section décrit ce qui n'appartient à aucun module mais conditionne tous : les moteurs génériques et l'abstraction comptable. C'est ici que se joue la différence entre une refonte durable et un habillage. Sans moteur de vues, chaque écran de liste serait recodé ; sans abstraction comptable, le PCG 2005 resterait une adaptation fragile d'un socle SYSCOHADA.

### 12.1 Moteurs génériques

| Moteur | Ce qu'il fait | Ce qu'il évite de recoder |
|---|---|---|
| **Moteur de vues** | Une définition déclarative par vue (modèle, type, colonnes, actions, filtres par défaut, rôles autorisés), stockée en base. Le composant c-data-grid la consomme. | Une trentaine d'écrans de liste spécifiques en Phase 1, et l'essentiel des écrans des phases 2 et 3. |
| **Moteur de recherche et de filtre** | Traduction d'un ensemble de critères en requête ORM sûre, avec regroupements et sauvegarde de vues personnelles ou partagées. | Un formulaire de filtre spécifique par écran, et la tentation de construire du SQL dynamique. |
| **Moteur de workflow** | États, transitions, conditions, permission requise, effets de bord. Alimente automatiquement le chatter et l'audit. | La logique d'état dupliquée dans chaque module (devis, commande, facture, opportunité), puis dans les OF et contrôles qualité en Phase 3. |
| **Chatter et activités** | Fil attachable à n'importe quel objet : messages, notes internes, activités planifiées, abonnés, historique des transitions. | Un système de commentaires et de rappels par module. |
| **Notifications** | Modèle abstrait destinataire / gabarit / canal / statut, avec réessai. Canal e-mail et canal interne en Phase 1. | La refonte du modèle de notification à l'arrivée de WhatsApp en Phase 2. |
| **Permissions par rôle** | Matrice rôle × action évaluée côté serveur, pilotant aussi la composition du launchpad et du sélecteur d'applications. | Les vérifications d'autorisation dispersées et incomplètes. |
| **Audit** | Journal non modifiable des événements sensibles, alimenté par les autres moteurs plutôt que par des appels manuels. | L'oubli systématique de journaliser, qui est la règle quand la journalisation est manuelle. |
| **Import / export** | Chaîne générique : dépôt de fichier, correspondance de colonnes, validation, prévisualisation des erreurs, import par lots avec rapport. | Un import spécifique par entité, et le recours au support pour toute reprise de données. |

### 12.2 Abstraction du référentiel comptable

**Madagascar n'est pas membre de l'OHADA.** Le pays applique le Plan Comptable Général 2005, adopté par le décret n° 2004-272 du 18 février 2004 et cohérent avec les normes internationales IAS/IFRS. Le SYSCOHADA révisé est le référentiel des États membres de l'OHADA (Côte d'Ivoire, Sénégal, Cameroun, Bénin, Togo…). Ce sont deux référentiels distincts : plan de comptes, états financiers et logiques de retraitement diffèrent. Toute confusion entre les deux produit une comptabilité non conforme. Cette distinction est un invariant du produit, pas un détail de paramétrage.

La base de code d'origine étant orientée SYSCOHADA, la Phase 1 introduit une couche d'abstraction qui fait du référentiel une donnée et non une hypothèse de code. Le tenant porte un pays, le pays détermine le référentiel actif, et toutes les écritures référencent un compte appartenant à ce référentiel.

****Modèle d'abstraction comptable — livré en Phase 1****

```
core_accounting_framework
   id, code            ← PCG2005 | SYSCOHADA_REVISE
   libelle, pays_defaut, actif, version_norme
        │ 1..n
        ▼
core_chart_of_accounts   (un plan de comptes par référentiel et par pays)
   id, framework_id, pays, libelle, date_effet
        │ 1..n
        ▼
core_account
   id, chart_id, numero, libelle, classe, type, lettrable, collectif
        ▲ référencé par
        │
acc_journal_entry_line ── acc_journal_entry ── acc_journal
core_account_mapping  (transposition entre référentiels — prépare l'OHADA)
   id, framework_source, framework_cible, compte_source, compte_cible
RÈGLE : tenant → pays → framework actif → plan de comptes → comptes autorisés.
Aucun numéro de compte n'apparaît en dur dans le code applicatif ; les comptes
utilisés par les automatismes (TVA, client, vente) passent par une table de
comptes par défaut paramétrable par tenant.
```

La table de transposition core_account_mapping n'a aucune utilité immédiate en Phase 1, où un seul référentiel est actif. Elle est livrée malgré tout parce que son coût est faible maintenant et qu'elle sera la pièce centrale du déploiement OHADA : sans elle, l'ajout de la Côte d'Ivoire imposerait de reprendre le modèle d'écritures.

### 12.3 Paramètres réglementaires versionnés

Aucun taux, seuil, plafond ou barème n'est écrit dans le code. Tous vivent dans core_regulatory_parameter, lue à la date de l'opération. Ce n'est pas une précaution de style : une loi de finances change chaque année, et un ERP qui exige un redéploiement de code pour appliquer un nouveau barème est ingérable.

****Structure de la table de paramètres****

core_regulatory_parameter

id

pays MG

type TVA | IRSA | CNAPS | OSTIE | FMFP | SME | SEUIL | AUTRE

cle identifiant stable, ex. 'tva.taux_normal'

valeur numérique ou JSON (barème à tranches)

unite pourcentage | MGA | multiple

date_effet date à partir de laquelle le paramètre s'applique

date_fin NULL = en vigueur

source référence du texte (loi, décret, arrêté)

statut_validation NON_VALIDE | VALIDE_OECFM

valide_par, valide_le

version incrémentée à chaque correction

• Lecture toujours à une date donnée : get(cle, date_operation).

• Aucune ligne n'est modifiée : une correction crée une nouvelle version.

• Un paramètre NON_VALIDE est utilisable en pré-production mais l'écran

signale l'état à l'utilisateur et la mise en production est bloquée par CI.

Le jeu de paramètres ci-dessous constitue l'amorçage livré avec la Phase 1. Les valeurs relatives à la paie (IRSA, CNaPS, OSTIE, FMFP) ne servent aucun écran de Phase 1, le module Paie étant en Phase 3 : elles sont chargées dès maintenant pour être soumises à la validation OECFM en même temps que les paramètres fiscaux, en une seule sollicitation de l'expert-comptable plutôt que deux.

| Clé | Valeur d'amorçage | Portée | Statut |
|---|---|---|---|
| **tva.taux_normal** | 20 % | Utilisé par Sales et Accounting dès la Phase 1. | À valider OECFM |
| **tva.taux_export** | 0 % | Exportations. | À valider OECFM |
| **tva.seuil_assujettissement** | 400 000 000 MGA de CA annuel HT | Détermine l'assujettissement du tenant. Une option d'assujettissement existe pour un CA compris entre 200 et 400 millions ; en deçà de 200 millions, régime de l'impôt synthétique. | À valider OECFM |
| **sme.montant** | 262 680 MGA (mars 2024 → fév. 2026) ; 300 000 MGA (mars → sept. 2026) ; 315 000 MGA (à partir d'oct. 2026) | Trois versions datées. Sert de base au plafond social. | À valider OECFM |
| **social.plafond_multiple_sme** | 8 × SME | Calculé dynamiquement, jamais stocké en valeur absolue. Le plafond suit automatiquement chaque révision du SME. | À valider OECFM |
| **cnaps.taux_salarie / cnaps.taux_employeur** | 1 % / 13 % | Assiette plafonnée au plafond social. [HYPOTHÈSE H2 — des sources secondaires citent un taux employeur plus ancien divergent.] | À valider OECFM — divergence |
| **ostie.taux_salarie / ostie.taux_employeur** | 1 % / 5 % | Même plafond. | À valider OECFM |
| **fmfp.taux_employeur** | 1 % | Formation professionnelle. Part salarié nulle. | À valider OECFM |
| **irsa.bareme** | Barème à tranches, deux versions datées (voir tableau ci-dessous) | Stocké en JSON pour supporter l'ajout ou le retrait de tranches sans migration. | À valider OECFM |
| **irsa.reduction_par_personne_a_charge** | 2 000 MGA | Par personne à charge et par mois. | À valider OECFM |
| **irsa.minimum_perception** | 3 000 MGA | Montant minimum dû par employé et par mois, quels que soient les revenus et réductions. | À valider OECFM |

### Barème IRSA — deux versions chargées

| Tranche de revenu imposable (MGA) | Taux — version 2025 | Taux — version 2026 |
|---|---|---|
| **0 – 350 000** | 0 % | 0 % |
| **350 001 – 400 000** | 5 % | 5 % |
| **400 001 – 500 000** | 10 % | 10 % |
| **500 001 – 600 000** | 15 % | 15 % |
| **600 001 – 4 000 000** | 20 % | 20 % |
| **Au-delà de 4 000 000** | 20 % | **25 % — tranche nouvelle** |

> La tranche à 25 % au-delà de 4 millions d'ariary résulte de la loi de finances pour 2026 et s'applique aux revenus à compter du 1er janvier 2026. La base imposable s'entend après déduction des cotisations CNaPS et OSTIE salarié. Ces éléments servent l'amorçage de la table et non un calcul de Phase 1 ; ils doivent être confirmés par l'expert-comptable avant tout usage en production.

**Verrou de mise en production.** Un test d'intégration continue empêche tout déploiement en production si un paramètre utilisé par un calcul actif porte le statut NON_VALIDE. La validation par un expert-comptable membre de l'OECFM n'est donc pas une bonne pratique documentaire : c'est une condition technique de déploiement. Elle est planifiée au sprint 18.

## 13. Spécifications fonctionnelles — Phase 1

CRM • Sales • Accounting • POS • Simulation • IA

Chaque module est décrit par son périmètre, ses écrans, ses règles de gestion structurantes et ses critères d'acceptation. Les critères sont formulés pour être directement traduisibles en tests automatisés : un critère que l'on ne peut pas exécuter ne sert à rien en recette.

### 13.1 Module CRM

**Objectif** : donner au commercial une vision complète du client sur un seul écran et supprimer les relances oubliées, qui sont la première perte de chiffre d'affaires d'une PME. La référence d'expérience est HubSpot : pipeline visuel, saisie légère, activités qui remontent d'elles-mêmes.

| Écran | Contenu et interactions |
|---|---|
| **Pipeline des opportunités** | Vue kanban par étape de vente, cartes affichant client, montant, date de clôture prévue et prochaine activité. Déplacement d'une carte par glisser-déposer déclenchant la transition d'état. Totaux pondérés par colonne. Bascule vers la vue liste et le tableau croisé sur le même filtre. |
| **Fiche société** | Page objet : en-tête d'identité (raison sociale, identifiant fiscal, encours, solde), onglets Contacts, Opportunités, Documents de vente, Comptabilité (solde et échéances), chatter latéral. C'est l'écran qui doit rendre inutile l'ouverture de trois autres. |
| **Fiche contact** | Personne rattachée à une société, fonction, coordonnées, préférences de contact, historique des échanges. |
| **Pistes** | Entrée légère avant qualification, avec conversion en société + contact + opportunité en une action, sans ressaisie. |
| **Activités** | Liste consolidée des activités planifiées de l'utilisateur, triées par échéance, avec traitement direct depuis la liste. Alimentée par le moteur d'activités commun. |
| **Tableau de bord commercial** | Tuiles : affaires en cours par étape, taux de transformation, chiffre d'affaires signé du mois, relances en retard. |

**Règles de gestion**

- Une opportunité est toujours rattachée à une société ; un contact orphelin est autorisé mais signalé dans le rapport de qualité des données.
- La création d'une société déclenche une détection de doublon sur la raison sociale et l'identifiant fiscal, avec proposition de fusion plutôt que blocage.
- Le passage d'une opportunité à l'état gagnée propose la création du devis correspondant, sans l'imposer.
- La suppression d'une société référencée par un document comptable est impossible ; elle peut être archivée.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **CRM-1** | Depuis le pipeline, déplacer une opportunité d'une colonne à l'autre met à jour son étape, inscrit la transition dans le chatter et dans le journal d'audit, sans rechargement complet de la page. |
| **CRM-2** | La fiche société affiche, sans navigation supplémentaire, l'encours, le solde comptable et les trois derniers documents de vente. |
| **CRM-3** | La conversion d'une piste crée la société, le contact et l'opportunité en une seule validation, sans ressaisie d'aucun champ déjà renseigné. |
| **CRM-4** | Une opportunité sans activité planifiée depuis plus de N jours (N paramétrable) apparaît dans la tuile « relances en retard » du launchpad. |
| **CRM-5** | L'écran pipeline vide affiche un état vide pédagogique proposant la création d'une opportunité et l'import d'un fichier, jamais un tableau vide sans message. |
| **CRM-6** | Un commercial ne voit que les sociétés de son portefeuille ; la restriction est vérifiée côté serveur, y compris par appel direct de l'endpoint de fragment. |
| **CRM-7** | Le parcours UC1 est réalisable en moins de 90 secondes et en moins de 12 clics. |

### 13.2 Module Sales

**Objectif** : la chaîne devis → commande → livraison → facture, sans ressaisie et sans rupture avec la comptabilité. C'est le module le plus utilisé en volume, donc celui où l'ergonomie de saisie a le plus d'impact économique.

| Écran | Contenu et interactions |
|---|---|
| **Catalogue** | Articles, familles, unités de mesure, prix de vente, taux de TVA par article. Prise en charge dès la Phase 1 des variantes (indispensable au textile) et des unités multiples avec conversions (indispensable à l'agroalimentaire) : ces deux notions sont structurelles et ne peuvent pas être ajoutées après coup. |
| **Tarification** | Listes de prix par client ou par catégorie, remises en ligne et en pied de document, gestion des prix en devise pour les clients export avec taux de conversion daté. |
| **Devis** | Page objet avec éditeur de lignes optimisé clavier : ajout d'une ligne, recherche d'article à la frappe, quantité, remise, totaux recalculés côté serveur. Duplication d'un devis existant. Génération du PDF et envoi tracé. |
| **Commande client** | Issue d'un devis accepté ou créée directement. Suivi des livraisons partielles et du reste à livrer. |
| **Bon de livraison** | Document de sortie, total ou partiel, imprimable. Le lien avec le stock réel est préparé mais la gestion de stock complète relève de la Phase 3. |
| **Facture et avoir** | Facturation totale, partielle ou par acompte. Numérotation continue non modifiable. Génération automatique de l'écriture comptable. Avoir par contre-passation ; aucune suppression de facture validée. |
| **Suivi des règlements** | Encaissements, soldes clients, balance âgée, relances. Point de jonction avec le lettrage comptable. |

**Règles de gestion**

- La TVA est toujours lue dans core_regulatory_parameter à la date du document, jamais saisie librement ni codée en dur.
- Une facture validée est immuable : correction par avoir, jamais par modification. La numérotation est continue, sans trou, garantie par une contrainte de base.
- L'écriture comptable est générée à la validation de la facture, selon les comptes par défaut paramétrés pour le tenant (vente, TVA collectée, client) issus du plan PCG 2005.
- Les montants en Ariary sont arrondis selon une règle unique définie une fois, et le total du document fait foi sur la somme des lignes.
- Un document ne peut porter une date située dans un exercice comptable clos.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **SAL-1** | Créer un devis de 5 lignes est réalisable entièrement au clavier, sans souris, et en moins de 2 minutes (parcours UC2). |
| **SAL-2** | La transformation d'un devis accepté en commande puis en facture ne demande aucune ressaisie de ligne, de prix ni de conditions. |
| **SAL-3** | La validation d'une facture génère une écriture équilibrée, dans le journal des ventes, avec les comptes PCG 2005 paramétrés, et rend la facture non modifiable. |
| **SAL-4** | Une tentative de modification ou de suppression d'une facture validée est refusée côté serveur, y compris par appel direct de l'API. |
| **SAL-5** | Le taux de TVA appliqué provient de la table de paramètres à la date du document ; un test vérifie qu'aucun taux n'est écrit en dur dans le code du module. |
| **SAL-6** | La numérotation des factures est continue même en cas de créations simultanées (test de concurrence). |
| **SAL-7** | Une interruption réseau pendant la saisie d'un devis ne fait perdre aucune ligne déjà saisie après rechargement de la page (principe P4). |
| **SAL-8** | Le PDF généré comporte toutes les mentions obligatoires paramétrées pour le tenant et affiche les montants en Ariary selon la règle unique de présentation. |

### 13.3 Module Accounting

**Objectif** : produire une comptabilité conforme au PCG 2005, auditable, et suffisamment confortable pour qu'un comptable préfère WideHalo à son tableur. C'est le module le plus exigeant en conformité et le seul dont un défaut peut avoir des conséquences légales pour le client.

| Écran | Contenu et interactions |
|---|---|
| **Plan de comptes** | Plan PCG 2005 chargé par défaut à la création d'un tenant malgache, extensible par le client sur les comptes de détail. Recherche instantanée par numéro ou libellé. Comptes par défaut du tenant (vente, achat, TVA, client, fournisseur, banque, caisse). |
| **Journaux** | Ventes, achats, banque, caisse, opérations diverses, à nouveaux. Paramétrage des contreparties et des séquences de numérotation. |
| **Saisie d'écriture** | Écran le plus dense de l'application : saisie en grille, navigation clavier complète, recherche de compte à la frappe, contrepartie proposée, contrôle d'équilibre en continu, duplication d'écriture, modèles d'écriture récurrente. |
| **Lettrage** | Rapprochement des écritures clients et fournisseurs, lettrage automatique par montant et référence, lettrage manuel assisté, délettrage tracé. |
| **Rapprochement bancaire** | Import d'un relevé, rapprochement des lignes, état de rapprochement imprimable. |
| **Déclaration de TVA** | Calcul de la TVA collectée et déductible sur la période, état détaillé justifiant chaque montant, génération de l'écriture de liquidation. |
| **États financiers** | Balance générale et auxiliaire, grand livre, journal, bilan et compte de résultat au format PCG 2005, à l'écran et à l'export. |
| **Clôture d'exercice** | Contrôles préalables bloquants, génération des à-nouveaux, verrouillage définitif de l'exercice. |
| **Paramètres réglementaires** | Consultation et gestion de core_regulatory_parameter : valeur, date d'effet, source du texte, statut de validation. Écran destiné à l'expert-comptable externe. |

**Règles de gestion**

- Une écriture non équilibrée ne peut pas être enregistrée ; la contrainte est portée par la base de données, pas seulement par l'interface.
- Une écriture validée n'est jamais modifiée ni supprimée : correction par contre-passation, intégralement tracée.
- Aucun numéro de compte n'apparaît en dur dans le code : les automatismes passent par les comptes par défaut du tenant, eux-mêmes rattachés au plan du référentiel actif.
- Les états financiers sont produits selon la structure du référentiel actif du tenant (PCG 2005 pour Madagascar), jamais selon une structure codée en dur.
- Un exercice clos est en lecture seule pour tous les rôles, sans exception ni contournement administrateur.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **ACC-1** | À la création d'un tenant dont le pays est Madagascar, le référentiel actif est PCG 2005 et le plan de comptes correspondant est chargé automatiquement. |
| **ACC-2** | Un test vérifie qu'aucun numéro de compte ni structure d'état financier n'est écrit en dur dans le code applicatif. |
| **ACC-3** | La saisie d'une écriture de 4 lignes est réalisable entièrement au clavier (parcours UC4), avec proposition de contrepartie et contrôle d'équilibre en continu. |
| **ACC-4** | L'enregistrement d'une écriture déséquilibrée est refusé par la base de données elle-même, même en contournant l'interface. |
| **ACC-5** | Le lettrage automatique traite les cas de montant identique et de référence commune, et laisse les autres cas au lettrage manuel sans les traiter à tort. |
| **ACC-6** | La déclaration de TVA d'une période se rapproche à l'ariary près de la somme des écritures de TVA de la période, avec un état justificatif ligne à ligne. |
| **ACC-7** | Le bilan et le compte de résultat sont produits au format PCG 2005 et exportables. |
| **ACC-8** | Toute modification d'un paramètre réglementaire crée une nouvelle version, conserve la précédente et apparaît dans le journal d'audit. |
| **ACC-9** | Le déploiement en production échoue si un paramètre utilisé par un calcul actif porte le statut NON_VALIDE. |
| **ACC-10** | Un exercice clos refuse toute écriture, y compris par appel direct de l'API et y compris pour un utilisateur administrateur. |

### 13.4 Module IA — copilote WideHalo

**Objectif** : permettre à un dirigeant de PME d'obtenir une réponse de gestion sans savoir quel rapport ouvrir, et à un utilisateur intensif de gagner du temps sur la rédaction et la synthèse. Le copilote est un confort augmenté, jamais un chemin critique : l'ERP doit rester intégralement utilisable s'il est indisponible.

****Chaîne d'exécution du copilote****

```
Utilisateur
   │ question en langage naturel
   ▼
WideHalo (Django) ── contexte : tenant, rôle, écran courant
   │
   ▼ HTTP interne
widehalo-ai-gateway (FastAPI)
   ├─> Ollama local (CPU) — backend par défaut
   └─> API cloud — repli, activation explicite
   │  le modèle PROPOSE un appel d'outil
   ▼
┌────────────────────────────────────────────────────────────────┐
│ CONTRÔLEUR D'OUTILS — côté code, jamais côté modèle            │
│   ✓ l'outil figure-t-il dans la liste blanche ?                │
│   ✓ le rôle de l'utilisateur autorise-t-il cet outil ?         │
│   ✓ les paramètres respectent-ils le schéma et les bornes ?    │
│   ✓ le tenant est-il bien celui de la session ?                │
└────────────────────────────────────────────────────────────────┘
   │ si et seulement si les quatre contrôles passent
   ▼
API django-ninja — endpoints LECTURE SEULE de la liste blanche
   │
   ▼
PostgreSQL (RLS active, rôle applicatif non superutilisateur)
⚠  AUCUN chemin du modèle vers PostgreSQL.
   AUCUN SQL généré. AUCUNE écriture possible.
```

**Interdiction du text-to-SQL — principe d'architecture, pas précaution temporaire.** Laisser un modèle de langage produire du SQL sur une base d'ERP cumule trois défauts rédhibitoires : il expose à l'injection de prompt (un libellé de facture peut contenir une instruction), il court-circuite toute la logique métier (un chiffre d'affaires calculé en SQL brut ignore les avoirs, les remises et les exercices), et il rend l'isolation multi-tenant dépendante de la prudence du modèle. L'approche par outils en liste blanche coûte plus cher à construire et donne des réponses moins « magiques », mais elle est la seule qui reste sûre et juste.

**Outils exposés en Phase 1**

| Outil | Ce qu'il retourne | Rôles autorisés |
|---|---|---|
| **rechercher_tiers** | Sociétés et contacts correspondant à un critère, avec identifiants internes. | Tous |
| **etat_client** | Solde, encours, balance âgée et derniers documents d'un client. | Commercial, ADV, Comptable, Dirigeant |
| **pipeline_resume** | Opportunités par étape, montants pondérés, affaires sans activité planifiée. | Commercial, Dirigeant |
| **ventes_periode** | Chiffre d'affaires sur une période, ventilé par client, article ou famille — calculé par la logique métier, pas par une requête ad hoc. | Commercial, ADV, Comptable, Dirigeant |
| **documents_en_attente** | Devis à relancer, commandes non livrées, factures échues. | Commercial, ADV, Comptable, Dirigeant |
| **solde_comptes** | Soldes de comptes ou de classes du plan actif sur une période. | Comptable, Dirigeant |
| **parametre_reglementaire** | Valeur d'un paramètre à une date, avec sa source et son statut de validation. | Comptable, Dirigeant |
| **etat_caisse** | Sessions de caisse ouvertes, encaissements du jour par moyen de paiement, écarts constatés, ventes en attente de synchronisation. | Caissier (sa caisse), Comptable, Dirigeant |
| **parametrer_simulation** | Traduit une question en langage naturel en un jeu de leviers et le transmet au moteur de simulation. Ne calcule rien et ne retourne aucun chiffre : le moteur déterministe produit les valeurs. | Contrôleur de gestion, Dirigeant |
| **expliquer_ecran** | Aide contextuelle sur l'écran courant, à partir de la documentation produit. | Tous |

**Fonctions de rédaction assistée**

Trois usages complémentaires, sans accès aux outils de données : résumer un fil de discussion long sur une opportunité ; proposer un brouillon de message de relance client à partir du contexte de l'affaire ; reformuler un texte saisi par l'utilisateur. Dans les trois cas, la production du modèle est un brouillon soumis à validation humaine, jamais envoyé ni enregistré automatiquement.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **IA-1** | Un test de CI échoue si un endpoint accessible au gateway autorise une méthode d'écriture ou ne figure pas dans la liste blanche déclarée. |
| **IA-2** | Tout appel d'outil est journalisé dans le journal d'audit avec l'utilisateur, le tenant, l'outil, les paramètres et la durée. |
| **IA-3** | Un utilisateur ne peut obtenir, via le copilote, aucune donnée qu'il ne pourrait consulter dans l'interface avec son rôle (test avec un compte commercial interrogeant des données comptables). |
| **IA-4** | Une donnée d'un autre tenant n'est jamais retournée, même si la question la nomme explicitement (test d'isolation avec deux tenants). |
| **IA-5** | Une instruction hostile insérée dans un champ de données (nom de société, libellé d'écriture) ne provoque aucun appel d'outil hors liste blanche ni aucune écriture. |
| **IA-6** | Le gateway arrêté, l'ERP reste intégralement fonctionnel et le copilote affiche un message d'indisponibilité clair, sans erreur technique. |
| **IA-7** | Le délai de réponse est borné ; au-delà du seuil, l'utilisateur reçoit une réponse d'attente explicite plutôt qu'une page bloquée. |
| **IA-8** | Chaque réponse chiffrée du copilote fournit le lien vers l'écran ou l'état qui permet de vérifier le chiffre. |
| **IA-9** | Le repli vers un fournisseur cloud est désactivé par défaut ; son activation affiche explicitement quelles données sortiront du serveur et est journalisée. |

### 13.5 Module POS — distribution et services

**Objectif** : encaisser en point de vente et en prestation de service, y compris lorsque le réseau ou l'électricité font défaut, et faire retomber automatiquement chaque encaissement en comptabilité. Le POS est le module qui met l'ERP au contact du client final ; c'est aussi celui où une panne est immédiatement visible — une caisse bloquée, c'est une file d'attente et une vente perdue.

Deux usages sont couverts par le même module, avec le même catalogue et la même tarification que Sales :

- **POS distribution** — boutique, show-room, dépôt : articles et variantes, code-barres, sortie de stock, ticket ou facture.
- **POS services** — prestation, façon, atelier, réparation, intervention : lignes de service sans référence de stock, au forfait ou au temps passé, avec acompte possible.

| Écran | Contenu et interactions |
|---|---|
| **Écran de vente (caisse)** | Plein écran, conçu tactile et clavier : recherche article à la frappe ou au scan, panier, quantités, remise ligne et remise ticket, client optionnel, mise en attente et reprise d'un ticket. Cibles ≥ 44 px, contraste élevé, aucun élément nécessitant la souris. |
| **Paiement** | Multi-moyens et paiement mixte : espèces avec calcul du rendu en coupures Ariary, mobile money (Mvola, Orange Money, Airtel Money) avec référence de transaction obligatoire, carte, chèque, avoir et acompte. Chaque moyen est relié à un compte du plan PCG 2005 paramétré par tenant. |
| **Session de caisse** | Ouverture avec fond de caisse, mouvements d'espèces entrants et sortants motivés, clôture avec comptage physique et écart constaté. La session est l'unité de responsabilité du caissier. |
| **Ticket et facture** | Ticket simplifié ou facture nominative avec mentions obligatoires paramétrées. Réimpression autorisée mais tracée et marquée comme duplicata. |
| **Retour, échange, avoir** | Retour partiel ou total rattaché au ticket d'origine, échange avec complément ou remboursement, avoir réutilisable en moyen de paiement. |
| **Prestation de service** | Bon d'intervention, lignes au forfait ou au temps passé, acompte à la commande et solde à l'achèvement, sans aucune référence de stock. |
| **Back-office POS** | Points de vente, caisses, caissiers et droits, moyens de paiement et comptes associés, journal des écarts de caisse, consolidation multi-points de vente, journal de synchronisation. |

**Règles de gestion**

- Aucune vente n'est possible en dehors d'une session de caisse ouverte ; la session close est immuable, y compris pour un administrateur.
- Tout écart de caisse est enregistré, motivé et journalisé — jamais absorbé silencieusement.
- La clôture de session génère l'écriture comptable consolidée sur les comptes paramétrés par moyen de paiement (caisse, banque, comptes de monnaie électronique).
- Les prix proviennent de la tarification de Sales : il n'existe pas de second catalogue ni de seconde grille de prix pour le POS.
- Un ticket anonyme est autorisé ; une facture nominative exige un tiers identifié.
- En Phase 1, la sortie de stock est enregistrée comme mouvement indicatif réconcilié à l'inventaire ; le rattachement au module Stock complet relève de la Phase 3.

**Le POS est le seul écran de la Phase 1 conçu « hors ligne d'abord ».** Catalogue, tarifs et session sont mis en cache local ; les ventes réalisées sans réseau sont mises en file et synchronisées à la reconnexion. La numérotation combine un préfixe de caisse et une séquence locale, réconciliée côté serveur : ni trou, ni doublon. En cas de divergence, la vente locale fait foi et le serveur ne la réécrit jamais ; l'écart est porté au journal de synchronisation. La limite est dite à l'utilisateur plutôt que masquée : une caisse hors ligne ne connaît pas les règlements enregistrés ailleurs, donc l'encours d'un client n'y est pas garanti.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **POS-1** | Une vente de trois articles payée en espèces avec rendu de monnaie s'exécute en moins de 30 secondes, entièrement au tactile ou au clavier, sans souris (parcours UC6). |
| **POS-2** | Toute tentative de vente hors session de caisse ouverte est refusée côté serveur. |
| **POS-3** | Réseau coupé : la vente aboutit, le ticket est produit, et la synchronisation à la reconnexion n'entraîne ni perte ni double comptabilisation (test de coupure puis de reprise). |
| **POS-4** | La numérotation des tickets est continue par caisse, sans trou ni doublon, y compris après une période hors ligne et en créations concurrentes. |
| **POS-5** | Un paiement mixte espèces + mobile money est accepté ; la référence de transaction du mobile money est obligatoire et conservée avec la vente. |
| **POS-6** | La clôture de session impose un comptage ; tout écart est enregistré avec motif et apparaît au journal d'audit et à l'écran de contrôle. |
| **POS-7** | La clôture génère une écriture équilibrée sur les comptes PCG 2005 paramétrés pour chaque moyen de paiement. |
| **POS-8** | Une prestation de service se facture sans article physique ni référence de stock, avec gestion de l'acompte et du solde. |
| **POS-9** | Une session close refuse toute modification, y compris par appel direct de l'API et y compris pour un utilisateur administrateur. |

### 13.6 Module Simulation financière temps réel

**Objectif** : permettre au dirigeant et au contrôleur de gestion de répondre à « que se passe-t-il si… » sur les données réelles de l'entreprise, en quelques secondes et sans jamais toucher à la comptabilité. C'est le module qui transforme WideHalo d'un outil d'enregistrement en un outil de décision — et le seul dont la valeur dépende entièrement de sa réactivité : un simulateur qui met cinq secondes à répondre n'est pas utilisé.

| Écran | Contenu et interactions |
|---|---|
| **Atelier de scénarios** | Leviers manipulables (curseurs et champs) à gauche, indicateurs recalculés en continu à droite, écart par rapport à la référence affiché en permanence en valeur et en pourcentage. Aucun bouton « calculer » : le résultat suit la manipulation. |
| **Comparateur** | Deux à quatre scénarios côte à côte sur les mêmes indicateurs, avec mise en évidence des divergences. |
| **Bibliothèque de scénarios** | Scénarios nommés, datés, versionnés, personnels ou partagés, avec leur commentaire et leur auteur. |
| **Projection de trésorerie** | 13 semaines glissantes ou 12 mois, alimentée par l'encours client réel, les échéances fournisseurs et les leviers de délais de règlement. |
| **Point mort et sensibilité** | Seuil de rentabilité, couverture de trésorerie en jours, et classement des leviers par poids réel sur le résultat — pour savoir sur quoi agir en priorité. |

**Leviers et indicateurs de la Phase 1**

| Famille | Leviers manipulables | Indicateurs restitués |
|---|---|---|
| **Commercial** | Prix de vente (global, par famille, par article), volume, remise moyenne, mix produit. | Chiffre d'affaires, marge brute, taux de marge. |
| **Achats et production** | Coût matière, taux de change MGA/EUR/USD/CNY, coût de transport et droits à l'import. | Coût de revient, marge par famille, point mort. |
| **Structure** | Charges fixes, masse salariale, investissement, frais financiers. | Excédent brut d'exploitation, résultat, seuil de rentabilité. |
| **Trésorerie** | Délai de règlement client, délai fournisseur, échéancier d'investissement. | Besoin en fonds de roulement, trésorerie projetée, couverture en jours. |
| **Fiscal** | Taux de TVA et assujettissement, lus dans core_regulatory_parameter. | TVA nette projetée, impact sur la trésorerie. |

**Comment le « temps réel » est obtenu.** Un scénario n'interroge pas la base à chaque mouvement de curseur — ce serait inutilisable sur le réseau des clients. Le serveur construit une fois un **socle de simulation** : un modèle compact et agrégé (séries mensuelles de chiffre d'affaires, de marge, de charges et d'encours, par axe d'analyse), chargé en un seul appel. Le recalcul s'exécute ensuite localement sur ce modèle, ce qui donne une réponse immédiate même hors ligne. À l'enregistrement, le serveur recalcule et fait autorité ; toute divergence entre le calcul local et le calcul serveur bloque l'enregistrement et est signalée, plutôt que d'être absorbée.

**Garde-fous**

- **Un scénario n'est pas un budget.** Il ne crée aucune écriture, ne modifie aucun document et n'engage rien. L'interface le dit explicitement plutôt que de laisser l'ambiguïté s'installer entre prévision et engagement.
- **Traçabilité de la donnée source.** Chaque scénario enregistre la date d'extraction du socle, le périmètre retenu et la version des paramètres réglementaires utilisés : deux scénarios construits à deux mois d'écart ne sont comparables que si cette information est portée.
- **Rôle borné de l'IA.** Le copilote peut traduire une question en langage naturel en un jeu de leviers (« et si on baissait de 5 % les prix de la famille X ») mais ne produit jamais un chiffre : il paramètre le moteur déterministe, qui calcule. Toute valeur affichée provient du moteur, jamais du modèle de langage.
- **Isolement des données.** Le socle de simulation est borné au tenant et au rôle : un utilisateur ne peut simuler que sur le périmètre qu'il a le droit de consulter.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **SIM-1** | La modification d'un levier met à jour tous les indicateurs affichés en moins de 100 ms, mesuré sur un profil réseau dégradé. |
| **SIM-2** | Le socle de simulation est chargé en un seul appel et reste sous le budget de taille fixé pour le réseau cible. |
| **SIM-3** | Un scénario enregistré conserve la date d'extraction du socle, le périmètre et la version des paramètres réglementaires appliqués. |
| **SIM-4** | Le recalcul serveur à l'enregistrement redonne les mêmes valeurs que le calcul local à l'ariary près ; toute divergence bloque l'enregistrement et est signalée. |
| **SIM-5** | Aucune écriture comptable ni aucun document métier n'est créé ou modifié par le module (test : aucun endpoint d'écriture métier accessible depuis le moteur). |
| **SIM-6** | Deux à quatre scénarios sont comparables côte à côte, avec l'écart en valeur et en pourcentage par rapport à la référence. |
| **SIM-7** | La projection de trésorerie à 13 semaines intègre l'encours client réel, les échéances fournisseurs et les leviers de délais de règlement (parcours UC7). |
| **SIM-8** | Un scénario proposé par le copilote est exécuté par le moteur déterministe, et le journal d'audit relie la demande en langage naturel aux leviers effectivement appliqués. |
| **SIM-9** | Un utilisateur ne peut simuler que sur le périmètre de données que son rôle l'autorise à consulter (test avec deux rôles et deux tenants). |

## 14. Plan de développement — sprints hebdomadaires

29 semaines, 8 blocs, un incrément démontrable chaque vendredi

La cadence est d'un sprint par semaine. Ce rythme court est choisi pour une raison précise liée au développement assisté par IA : un agent produit vite, ce qui rend facile de partir loin dans une mauvaise direction. Une revue hebdomadaire bornée limite mécaniquement l'ampleur d'un écart. Chaque sprint se termine par un incrément visible à l'écran, jamais par « du travail en cours ».

### 14.1 Ordonnancement et dépendances

****Chaîne de dépendances des blocs****

```
 S1     S2→S8            S9→S11     S12→S15     S16→S19     S20→S23     S24→S26    S27→S28   S29
┌─────┬────────────────┬──────────┬───────────┬───────────┬───────────┬───────────┬────────┬─────┐
│ CAD │ A — SOCLE UX   │ B — CRM  │ C — SALES │ D — ACCT  │ E — POS   │ F — SIMU  │ G — IA │  H  │
└─────┴────────────────┴──────────┴───────────┴───────────┴───────────┴───────────┴────────┴─────┘
Le socle (bloc A) conditionne tous les blocs métier : aucun écran de CRM,
de Sales ou d'Accounting n'est construit avant que la bibliothèque de
composants et le moteur de vues ne soient livrés.
```

****Dépendances croisées à surveiller****

```
C (Sales) ───> D (Accounting)
   l'écriture comptable de facture (SAL-3) est codée en S15 mais désactivée
   par indicateur ; elle est activée et testée en S16, une fois le
   référentiel PCG 2005 livré.
C + D ───> E (POS)
   le POS réutilise le catalogue et la tarification de Sales, et déverse ses
   clôtures de caisse dans les comptes d'Accounting. Il ne peut pas être
   avancé avant S20.
C + D + E ───> F (Simulation)
   le socle de simulation agrège les ventes, la marge, les charges et
   l'encours : il lui faut des données complètes, POS inclus.
B…F ───> G (IA)
   les outils du copilote lisent les données de tous les modules ; le bloc IA
   reste volontairement en fin de plan.
A (S1) ───> D (Accounting)
   l'inventaire de l'existant peut révéler une dépendance profonde à
   SYSCOHADA et imposer de replanifier le bloc D (risque R1).
```

**Une seule dépendance croisée à surveiller.** Le module Sales génère des écritures comptables (SAL-3) alors que le référentiel comptable n'est livré qu'au sprint 16. La facturation du sprint 15 est donc développée avec la génération d'écriture désactivée par indicateur, puis activée et testée de bout en bout au sprint 16. L'alternative — placer Accounting avant Sales — a été écartée car elle retarderait de quatre semaines la première démonstration commerciale complète.

### 14.2 Bloc A — Cadrage et socle UX (S1 à S8)

Huit semaines sans aucune fonctionnalité métier nouvelle. C'est contre-intuitif et c'est le cœur du plan : construire les écrans avant les composants garantit de les reconstruire. Le bloc A produit malgré tout des livrables visibles chaque semaine — une galerie de composants navigable, puis le shell, puis le launchpad réel.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S1** | Cadrage et mesure de la ligne de base | INVENTAIRE_EXISTANT.md produit automatiquement (modèles, endpoints, écrans, workflows) et confronté aux budgets déclarés — lève H1. Chronométrage des parcours UC1 à UC5 sur l'interface actuelle et passation du questionnaire SUS de référence. Tests de CI de budget d'architecture en place. Squelette du routage à indicateurs (ancienne / nouvelle UI). Renommage complet ORION → WideHalo. | 4 | 1,5 |
| **S2** | Design system et fondations | Tokens (couleurs, espacements, rayons, ombres, durées) en variables CSS et configuration Tailwind ; thème clair et sombre ; infrastructure d'internationalisation ; premiers composants : c-button, c-badge, c-money, c-toast, c-skeleton, c-empty-state. Galerie de composants navigable. Test de CI interdisant les valeurs de style en dur. | 6 | 3 |
| **S3** | Shell applicatif et launchpad | Barre supérieure persistante, sélecteur d'applications, fil d'Ariane, menu utilisateur (langue, densité, thème). Launchpad avec c-tile statique, à compteur et à indicateur, favoris épinglables et documents récents. Tuiles chargées par un appel groupé unique. | 5 | 2,5 |
| **S4** | Recherche globale et notifications | c-search-palette (Ctrl/Cmd+K) : enregistrements, actions et navigation, résultats groupés. Moteur de notifications abstrait (destinataire / gabarit / canal / statut / réessai) avec canal interne et canal e-mail. File de tâches asynchrones opérationnelle. | 5 | 2,5 |
| **S5** | Data grid universel | c-data-grid complet : colonnes configurables et mémorisées, tri, pagination serveur, sélection multiple, actions de masse, colonnes figées, densité, états vide / chargement / erreur, export asynchrone. Composant le plus structurant du projet. | 7 | 3,5 |
| **S6** | Moteur de vues et filtres | Définitions de vues stockées en base ; c-view-switcher (liste, kanban, tableau croisé, calendrier) sur un même jeu de données ; c-filter-bar avec regroupements et vues sauvegardées personnelles ou partagées. Moteur de recherche et de filtre sûr (aucun SQL construit par concaténation). | 7 | 3,5 |
| **S7** | Formulaires et saisie de lignes | c-form à onglets avec validation en ligne champ par champ et sauvegarde de brouillon (principe P4) ; c-line-editor optimisé clavier avec ajout, duplication, réordonnancement et totaux serveur. Navigation clavier complète vérifiée. | 6 | 3 |
| **S8** | Workflow, chatter, permissions, audit | Moteur d'états déclaratif ; c-chatter attachable à tout objet (messages, notes internes, activités, abonnés) ; matrice rôle × action évaluée côté serveur pilotant le launchpad ; journal d'audit alimenté automatiquement par les moteurs. Test de CI listant les endpoints sans déclaration de permission. | 6 | 3 |

> Fin du bloc A — jalon J1 : la galerie de composants et le shell sont démontrables ; un écran de liste quelconque peut désormais être produit en quelques heures au lieu de plusieurs jours. Point de recalibrage des estimations (lève H5).

### 14.3 Bloc B — Module CRM (S9 à S11)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S9** | Pipeline et fiche société | Modèle CRM aligné sur le socle ; pipeline kanban avec transition par glisser-déposer (CRM-1) et totaux pondérés ; page objet Société avec en-tête, onglets et chatter (CRM-2) ; restriction par portefeuille commercial vérifiée côté serveur (CRM-6). | 6 | 2,5 |
| **S10** | Contacts, pistes, activités | Fiche contact ; pistes et conversion en une action sans ressaisie (CRM-3) ; liste consolidée des activités traitable directement ; détection de doublon avec proposition de fusion. | 5 | 2 |
| **S11** | Tableau de bord, import, bascule | Tableau de bord commercial et tuile « relances en retard » (CRM-4) ; chaîne d'import générique appliquée aux sociétés et contacts ; états vides pédagogiques (CRM-5) ; bascule des écrans CRM sur la nouvelle interface et suppression des écrans legacy correspondants ; mesure UC1 (CRM-7). | 5 | 2 |

> Fin du bloc B — jalon J2 : première démonstration client possible sur un parcours complet. Première mesure SUS post-refonte sur le périmètre CRM.

### 14.4 Bloc C — Module Sales (S12 à S15)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S12** | Catalogue et tarification | Articles, familles, unités de mesure et conversions (besoin agroalimentaire), variantes (besoin textile), taux de TVA par article lu dans la table de paramètres ; listes de prix par client, remises, devise et taux daté. | 6 | 2,5 |
| **S13** | Devis | Page objet Devis avec c-line-editor ; duplication ; workflow d'états ; génération du PDF en tâche asynchrone ; envoi tracé dans le chatter ; récupération de brouillon après coupure (SAL-7) ; mesure UC2 (SAL-1). | 6 | 2,5 |
| **S14** | Commande et livraison | Transformation devis → commande sans ressaisie (SAL-2) ; suivi du reste à livrer ; bons de livraison totaux et partiels ; points d'accroche du stock préparés pour la Phase 3 sans être activés. | 5 | 2 |
| **S15** | Facturation et règlements | Factures, avoirs, acomptes ; numérotation continue garantie en base et testée en concurrence (SAL-6) ; immutabilité de la facture validée (SAL-4) ; mentions obligatoires et présentation des montants (SAL-8) ; suivi des encaissements et balance âgée. Génération d'écriture codée mais désactivée par indicateur jusqu'à S16. | 7 | 3 |

> Fin du bloc C — jalon J3 : chaîne commerciale complète démontrable. Mesure UC2 et UC3.

### 14.5 Bloc D — Module Accounting (S16 à S19)

Bloc le plus sensible du plan : il porte la conformité et conditionne la mise en production commerciale. Il commence par l'abstraction, pas par les écrans — construire la saisie d'écriture sur un référentiel non abstrait obligerait à la reprendre.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S16** | Référentiel comptable et journaux | Modèle d'abstraction (framework / chart / account / mapping) ; chargement automatique du plan PCG 2005 pour un tenant malgache (ACC-1) ; comptes par défaut paramétrables ; journaux et séquences ; test interdisant tout numéro de compte en dur (ACC-2). Activation et test de bout en bout de l'écriture de facture (SAL-3). | 6 | 2,5 |
| **S17** | Saisie, lettrage, rapprochement | Écran de saisie d'écriture dense, entièrement clavier, avec contrepartie proposée et contrôle d'équilibre continu (ACC-3) ; contrainte d'équilibre en base (ACC-4) ; contre-passation ; lettrage automatique et manuel (ACC-5) ; import de relevé et rapprochement bancaire ; mesure UC4. | 7 | 3 |
| **S18** | Paramètres réglementaires et TVA | Table core_regulatory_parameter et écran de gestion destiné à l'expert-comptable ; chargement du jeu d'amorçage (TVA, SME, plafond social calculé, IRSA deux versions, CNaPS, OSTIE, FMFP) ; déclaration de TVA avec état justificatif (ACC-6) ; versionnement et audit (ACC-8) ; verrou de déploiement (ACC-9). Revue de validation OECFM — lève H2. | 5 | 2 |
| **S19** | États financiers et clôture | Balance générale et auxiliaire, grand livre, journal ; bilan et compte de résultat au format PCG 2005, à l'écran et à l'export (ACC-7) ; contrôles de clôture, à-nouveaux, verrouillage d'exercice opposable à tous les rôles (ACC-10). | 6 | 2,5 |

> Fin du bloc D — jalon J4 : conformité PCG 2005 démontrable devant un expert-comptable. C'est le jalon qui conditionne la commercialisation.

### 14.6 Bloc E — Module POS (S20 à S23)

Le POS réutilise le catalogue, la tarification et les comptes déjà livrés ; l'effort porte presque entièrement sur l'ergonomie de caisse et sur le fonctionnement hors ligne, qui est la partie techniquement la plus délicate de toute la Phase 1.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S20** | Écran de vente et session de caisse | Modèle POS (point de vente, caisse, session, ticket, ligne, règlement) ; écran de vente plein écran tactile et clavier, recherche et scan, panier, remises, mise en attente ; ouverture de session avec fond de caisse et mouvements d'espèces (POS-1, POS-2). | 7 | 3 |
| **S21** | Paiements et documents de caisse | Paiement multi-moyens et mixte : espèces avec rendu en coupures Ariary, mobile money avec référence obligatoire, carte, chèque, avoir (POS-5) ; ticket et facture nominative avec mentions paramétrées, réimpression tracée ; retour, échange et avoir réutilisable. | 6 | 2,5 |
| **S22** | Fonctionnement hors ligne | **Sprint le plus risqué du plan.** Cache local du catalogue, des tarifs et de la session ; file de ventes et synchronisation à la reconnexion sans double comptabilisation (POS-3) ; numérotation préfixe de caisse + séquence locale réconciliée (POS-4) ; journal de synchronisation ; message explicite sur les limites du mode hors ligne. | 7 | 3 |
| **S23** | Clôture, services, back-office | Clôture de session avec comptage et écart motivé (POS-6), écriture comptable consolidée par moyen de paiement (POS-7), immutabilité de la session close (POS-9) ; prestations de service au forfait ou au temps passé avec acompte (POS-8) ; back-office multi-points de vente, droits caissiers, journal des écarts. Mesure UC6. | 6 | 2,5 |

> Fin du bloc E — jalon J5 : encaissement démontrable en conditions réelles, réseau coupé compris. C'est le jalon qui ouvre le marché de la distribution et des services.

### 14.7 Bloc F — Simulation financière temps réel (S24 à S26)

Trois semaines dont l'essentiel de la difficulté est de modélisation, pas d'interface : définir un socle agrégé juste, compact et reproductible. Un moteur rapide sur un socle faux produit des décisions fausses plus vite.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S24** | Socle de simulation et moteur | Construction serveur du modèle agrégé (séries mensuelles de CA, marge, charges, encours par axe), chargé en un seul appel sous budget de taille (SIM-2) ; moteur de recalcul local avec réponse sous 100 ms (SIM-1) ; recalcul serveur faisant autorité à l'enregistrement avec blocage en cas de divergence (SIM-4). | 7 | 3 |
| **S25** | Atelier de scénarios et trésorerie | Leviers commerciaux, achats, structure, trésorerie et fiscaux ; indicateurs CA, marge, EBE, résultat, BFR, point mort ; projection de trésorerie à 13 semaines alimentée par l'encours réel et les échéances (SIM-7) ; écart permanent par rapport à la référence. | 6 | 2,5 |
| **S26** | Bibliothèque, comparateur, garde-fous | Scénarios nommés, versionnés et partageables avec traçabilité de la donnée source (SIM-3) ; comparateur de 2 à 4 scénarios (SIM-6) ; analyse de sensibilité et point mort ; cloisonnement par rôle et par tenant (SIM-9) ; test vérifiant qu'aucune écriture ni document n'est créé par le module (SIM-5). Mesure UC7. | 5 | 2,5 |

> Fin du bloc F — jalon J6 : le produit passe de l'enregistrement à l'aide à la décision. C'est l'argument commercial le plus différenciant face aux ERP généralistes.

### 14.8 Bloc G — Module IA (S27 et S28)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S27** | Gateway et outils | Microservice widehalo-ai-gateway ; intégration Ollama locale ; liste blanche d'outils en lecture seule et contrôleur d'outils côté code ; test de CI interdisant tout endpoint d'écriture accessible au gateway (IA-1) ; journalisation de chaque appel (IA-2). Banc d'essai de latence réelle — lève H4 et déclenche, si nécessaire, le repli sur un modèle plus petit ou sur l'API cloud. | 5 | 2 |
| **S28** | Copilote et garde-fous | Copilote intégré à l'interface, conscient de l'écran courant ; rédaction assistée (résumé, brouillon de relance, reformulation) toujours soumise à validation ; tests d'isolation multi-tenant (IA-4), de respect des rôles (IA-3) et d'injection de prompt (IA-5) ; quotas, délai maximal et dégradation explicite (IA-6, IA-7) ; lien de vérification sur toute réponse chiffrée (IA-8) ; repli cloud désactivé par défaut avec information explicite (IA-9). Mesure UC5. | 5 | 2 |

### 14.9 Bloc H — Durcissement et mise en production (S29)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S29** | Recette, durcissement, bascule | Audit d'accessibilité et corrections ARIA / focus / contraste (budget explicite, section 11.2) ; campagne de mesure de performance en réseau bridé ; tests de non-régression visuelle ; suppression des derniers écrans legacy du périmètre Phase 1 et abaissement du budget dédié ; restauration de sauvegarde testée ; vérification juridique H3 ; recette complète des critères CRM / SAL / ACC / POS / SIM / IA ; questionnaire SUS final et comparaison à la ligne de base ; mise en production. | 6 | 2,5 |

### 14.10 Répartition du travail entre l'humain et l'assistant IA

L'assistance IA ne déplace pas l'effort uniformément : elle est très efficace sur le code répétitif et bien spécifié, peu efficace là où le jugement métier domine. Le tableau suivant explicite cette répartition, qui est aussi la justification des ratios d'estimation de la section 15.

| Type de tâche | Délégué à l'assistant | Reste à la charge de l'humain | Gain |
|---|---|---|---|
| **Composants d'interface, écrans de liste et de formulaire dérivés du socle** | Génération complète à partir de la spécification de composant et du moteur de vues. | Revue visuelle, ajustement de densité et de libellés. | Élevé |
| **Tests automatisés des critères d'acceptation** | Écriture des tests à partir des critères numérotés de la section 13. | Vérification que le test échoue bien avant l'implémentation. | Élevé |
| **Migrations, sérialiseurs, endpoints CRUD, documentation technique** | Génération et mise en cohérence. | Relecture des migrations touchant à des données comptables. | Élevé |
| **Moteurs génériques (vues, workflow, filtres)** | Implémentation après conception validée. | Conception : c'est ici que se joue la qualité du socle ; déléguer la conception d'un moteur produit une abstraction plausible mais inadaptée. | Moyen |
| **Règles comptables et fiscales** | Mise en forme, tests, structure de données. | Intégralité de la décision métier, et validation par l'expert-comptable. Aucune valeur réglementaire n'est acceptée sur la seule proposition d'un assistant. | Faible |
| **Sécurité : RLS, permissions, confinement de l'IA** | Implémentation et tests. | Conception du modèle de menaces et revue ligne à ligne des garde-fous. | Faible |
| **Synchronisation hors ligne du POS** | Implémentation du cache, de la file et des tests de reprise. | Conception du protocole de réconciliation et arbitrage des conflits : une erreur ici produit des doublons comptables, pas un défaut d'affichage. | Faible |
| **Modélisation du socle de simulation** | Implémentation du moteur, des leviers et des tests de cohérence client/serveur. | Définition des agrégats et des formules : c'est un travail de contrôle de gestion, pas de développement. | Faible |
| **Arbitrages d'expérience utilisateur** | Propositions et variantes. | Décision, confrontée aux mesures (SUS, temps, clics) plutôt qu'à l'opinion. | Faible |

**Conditions pour que le gain se matérialise.** Le rendement de l'assistance IA dépend directement de trois choses que ce projet met en place volontairement : une spécification écrite et précise (ce document et les critères numérotés de la section 13), des garde-fous automatisés qui bornent le travail de l'agent sans supervision constante (tests, budgets d'architecture, interdictions vérifiées en CI), et une bibliothèque de composants qui rend chaque écran dérivable d'un modèle existant. Sans ces trois conditions, les ratios de la section 15 ne tiennent pas.

## 15. Estimation détaillée

Trois scénarios, hypothèses explicitées, ratios non calibrés signalés

### 15.1 Hypothèses de l'estimation

Une estimation sans hypothèses explicites n'est pas vérifiable et perd toute valeur dès que le contexte change. Celles-ci sous-tendent tous les chiffres qui suivent :

- Un seul développeur, maîtrisant déjà Django et le domaine métier, découvrant en revanche la bibliothèque de composants retenue.
- Environ 5 jours de travail effectif de développement par semaine, le reste du temps étant absorbé par le support, la relation client et la gestion du projet.
- Les lots transverses habituellement oubliés (environnement, tests, CI/CD, documentation, gestion de projet) sont inclus dans les chiffres par sprint, et non ajoutés ensuite.
- L'expert-comptable OECFM est disponible pour une revue au sprint 18 ; un décalage de sa disponibilité décale la mise en production, pas le développement.
- **[HYPOTHÈSE H5]** Les ratios entre effort classique et effort assisté utilisés ici ne sont pas calibrés sur des mesures réelles de ce projet. Ils reposent sur la nature des tâches (section 14.10) et sont donnés avec une fourchette large. Le sprint 4 sert de point de recalibrage à partir des données effectivement observées sur les sprints 1 à 4.

### 15.2 Synthèse par bloc

| Bloc | Sprints | J/H — voie classique | J-Token — génération | J/H — supervision humaine |
|---|---|---|---|---|
| **A — Cadrage et socle UX** | S1–S8 | 46 | 22,5 | 16 |
| **B — CRM** | S9–S11 | 16 | 6,5 | 5 |
| **C — Sales** | S12–S15 | 24 | 10 | 8 |
| **D — Accounting** | S16–S19 | 24 | 10 | 9 |
| **E — POS (distribution et services)** | S20–S23 | 26 | 11 | 9 |
| **F — Simulation financière** | S24–S26 | 18 | 8 | 7 |
| **G — IA** | S27–S28 | 10 | 4 | 3 |
| **H — Durcissement et mise en production** | S29 | 6 | 2,5 | 2 |
| **Total Phase 1** | **29** | **170** | **74,5** | **59** |

### 15.3 Lecture des deux unités

Le **Jour-Homme** mesure ce que coûterait la Phase 1 en développement classique : 170 J/H. Le **Jour-Token** mesure le volume de travail confié à l'assistant, exprimé en journées de session : 74,5 J-Token. Ces deux chiffres ne se remplacent pas, car le Jour-Token mesure mal trois choses qui ne disparaissent pas avec le développement assisté — elles se déplacent :

- le temps de clarification des exigences en amont, qui devient le véritable goulot d'étranglement d'un projet assisté (raison d'être de ce cahier des charges) ;
- le temps de relecture et de validation du code produit, incompressible sur les parties comptables et de sécurité ;
- le temps de correction quand l'agent part dans une mauvaise direction faute de contexte, que la cadence hebdomadaire sert précisément à borner.

C'est pourquoi la supervision humaine est estimée séparément à **59 J/H**. L'effort humain total de la voie assistée est donc de l'ordre de 59 J/H de supervision, contre 170 J/H en voie classique : le gain attendu est réel mais il porte sur la production de code, pas sur la conception ni sur la conformité.

### 15.4 Trois scénarios

| Scénario | J/H classique | J-Token | Supervision | Durée calendaire | Ce qui le déclenche |
|---|---|---|---|---|---|
| **Optimiste** | 138 | 61 | 48 | 24 semaines | L'inventaire du sprint 1 montre un existant plus propre que supposé ; la bibliothèque de composants est maîtrisée vite ; l'expert-comptable valide sans reprise. |
| **Réaliste** | 170 | 74,5 | 59 | 29 semaines | Scénario de référence du plan de la section 14. |
| **Pessimiste** | 235 | 108 | 82 | 40 semaines | L'inventaire révèle une dette structurelle sur le référentiel comptable (risque R1) ; le modèle local est trop lent et impose une reprise de l'architecture IA (H4) ; la synchronisation hors ligne du POS demande une reprise du protocole (R11) ; la validation OECFM impose des corrections de fond sur les paramètres. |

### 15.5 Marges appliquées par type de tâche

| Type de tâche | Marge | Justification |
|---|---|---|
| **Écrans dérivés du socle, CRUD, tests** | +10 à 20 % | Répétitif et bien cadré une fois la bibliothèque en place. |
| **Moteurs génériques (vues, workflow, filtres)** | +30 à 50 % | Nouveaux mais bien spécifiés ; le risque porte sur la justesse de l'abstraction, pas sur la difficulté technique. |
| **Abstraction comptable et paramètres réglementaires** | +50 à 100 % | Forte incertitude : dépend d'un existant non audité (H1) et d'une validation externe dont le résultat n'est pas maîtrisé (H2). |
| **Synchronisation hors ligne du POS** | +50 à 100 % | Forte incertitude : la réconciliation d'une file de ventes produites sans réseau est un problème de cohérence distribuée, dont les cas limites se découvrent en usage réel. |
| **Socle de simulation et moteur de recalcul** | +30 à 50 % | La difficulté est de modélisation, pas de code : la justesse des agrégats se valide avec un contrôleur de gestion, par itérations. |
| **Intégration IA et dimensionnement du modèle local** | +50 à 100 % | Dépend d'un banc d'essai matériel non encore réalisé (H4) ; l'échec du scénario local impose un changement d'approche, pas un ajustement. |

## 16. Risques et plan de mitigation

Ce qui peut faire dérailler la Phase 1

| Réf. | Risque | Impact | Prob. | Mitigation et signal d'alerte |
|---|---|---|---|---|
| **R1** | L'existant est plus éloigné de la cible que supposé : dépendance profonde à SYSCOHADA, modèle de données plus éloigné du besoin, budgets déjà dépassés. | Majeur | Élevée | Inventaire dès le sprint 1 (H1). Signal : plus de 20 % d'écart entre l'inventaire et les budgets déclarés → replanification immédiate du bloc D avant d'engager le bloc B. |
| **R2** | La validation OECFM impose des corrections de fond sur les paramètres ou la structure des états. | Majeur | Moyenne | Solliciter l'expert-comptable dès le sprint 16 pour une revue informelle, sans attendre la revue formelle du sprint 18. Le verrou de déploiement (ACC-9) garantit qu'une non-conformité bloque la production plutôt que d'y arriver. |
| **R3** | La migration écran par écran ne se termine jamais : ancienne et nouvelle interface coexistent indéfiniment, doublant la charge de maintenance. | Majeur | Élevée | Budget décroissant d'écrans legacy vérifié en CI (section 10.1) ; suppression du legacy inscrite dans la définition de fin des sprints 11 et 22. Signal : un budget non atteint deux sprints de suite. |
| **R4** | Le modèle local est trop lent sur CPU pour un usage conversationnel acceptable. | Moyen | Moyenne | Banc d'essai réel au sprint 27 (H4). Repli prévu par ordre de préférence : modèle plus petit, puis API cloud avec accord explicite du client. L'IA étant hors chemin critique, l'échec dégrade une fonctionnalité sans bloquer le produit. |
| **R5** | Fuite de données entre tenants par un filtre applicatif oublié. | Critique | Faible | RLS PostgreSQL comme garde-fou de dernière ligne, test de CI vérifiant que le rôle applicatif n'est ni superutilisateur ni exempté de RLS, et test d'isolation à deux tenants sur chaque module livré. |
| **R6** | Détournement du copilote IA : extraction de données hors périmètre ou action non autorisée via une instruction injectée dans les données. | Majeur | Moyenne | Aucun outil d'écriture n'existe ; contrôleur d'outils côté code, pas côté modèle ; tests d'injection (IA-5) ; journalisation intégrale des appels. Le confinement architectural rend l'attaque sans effet plutôt que difficile. |
| **R7** | Surcharge du développeur solo : le support client et la relation commerciale absorbent le temps de développement. | Majeur | Élevée | Estimation bâtie sur 5 jours effectifs par semaine et non 5 jours ouvrés. Signal : deux sprints consécutifs incomplets → réduction du périmètre de la Phase 1 plutôt que prolongation indéfinie du calendrier. |
| **R8** | Le code produit par l'assistant est plausible mais inadapté sur les parties de conception (moteurs, abstraction comptable). | Moyen | Moyenne | Conception réalisée par l'humain avant toute génération (section 14.10) ; critères d'acceptation écrits avant l'implémentation ; revue hebdomadaire bornée limitant l'ampleur d'un écart. |
| **R9** | Perte de données client : sauvegarde défaillante ou jamais testée. | Critique | Faible | Restauration réelle mensuelle obligatoire sur la pré-production (section 8.5) ; alerte immédiate sur échec de sauvegarde, traitée comme incident majeur. |
| **R10** | L'amélioration d'expérience n'est pas au rendez-vous : la nouvelle interface ne fait pas mieux que l'ancienne. | Majeur | Faible | Ligne de base mesurée au sprint 1, mesures intermédiaires aux jalons J2 et J3. Signal : gain inférieur à 15 % sur les tâches de référence au jalon J2 → revue de conception avant d'engager les blocs C et D. |
| **R11** | Le POS hors ligne produit des doublons ou perd des ventes à la synchronisation, ou sa numérotation présente des trous. | Critique | Moyenne | Protocole de réconciliation conçu par l'humain avant toute génération de code ; numérotation préfixe de caisse + séquence locale ; tests de coupure et de reprise automatisés (POS-3, POS-4) ; journal de synchronisation consultable. Signal : un seul écart non expliqué en recette → le sprint 22 est prolongé plutôt que la fonctionnalité livrée. |
| **R12** | Un scénario de simulation est pris pour un engagement, ou le calcul local diverge du calcul serveur sans que personne ne s'en aperçoive. | Majeur | Moyenne | Le module ne crée aucune écriture ni document (SIM-5, vérifié en CI) ; toute divergence client/serveur bloque l'enregistrement au lieu d'être absorbée (SIM-4) ; chaque scénario porte la date d'extraction et la version des paramètres (SIM-3) ; l'interface qualifie explicitement le résultat de projection, jamais de budget. |

## 17. Critères de recette et métriques de succès

Comment on saura que la Phase 1 est réussie

### 17.1 Recette fonctionnelle

La recette est constituée des critères numérotés de la section 13 : 7 critères CRM, 8 critères Sales, 10 critères Accounting, 9 critères POS, 9 critères Simulation et 9 critères IA, soit **52 critères**, tous automatisés. La Phase 1 est reçue lorsque l'intégralité de ces critères passe en intégration continue, sans exception tolérée : un critère écarté en recette est un critère qui n'aurait pas dû être écrit.

### 17.2 Recette technique — barrières bloquantes

| Barrière | Vérification automatisée |
|---|---|
| **Budgets d'architecture** | Modèles ≤ 230, endpoints ≤ 720, écrans ≤ 135, écrans legacy ≤ cible du sprint. |
| **Isolation multi-tenant** | Le rôle applicatif n'est ni superutilisateur ni exempté de RLS ; une requête sans tenant positionné renvoie zéro ligne. |
| **Conformité réglementaire** | Aucun taux, seuil ni numéro de compte en dur ; aucun paramètre NON_VALIDE utilisé par un calcul actif. |
| **Confinement de l'IA** | Aucun endpoint d'écriture accessible au gateway ; tous les outils déclarés dans la liste blanche ; tests d'injection et d'isolation au vert. |
| **Permissions** | Aucun endpoint sans déclaration de permission. |
| **Secrets** | Aucun secret détecté dans le code source. |
| **Design system** | Aucune couleur ni espacement en dur hors du fichier de tokens. |
| **Performance** | Budget de charge du chemin critique respecté ; temps de réponse des écrans de référence sous le seuil en profil réseau dégradé. |
| **Accessibilité** | Audit automatisé de contraste et de rôles ARIA sans anomalie bloquante. |
| **Intégrité du POS** | Aucune vente perdue ni doublée après coupure et reprise ; numérotation continue par caisse ; aucune modification possible sur session close. |
| **Innocuité de la simulation** | Aucun endpoint d'écriture métier atteignable depuis le moteur ; recalcul serveur identique au calcul local sur le jeu de référence. |
| **Sauvegarde** | Restauration réelle testée sur la pré-production dans les 30 jours. |

### 17.3 Métriques d'expérience utilisateur

L'objectif O1 est mesuré par le System Usability Scale, questionnaire standardisé à dix items. Sa valeur vient de sa comparabilité : un score isolé ne dit rien, un écart avant/après sur le même protocole dit beaucoup. C'est pourquoi la ligne de base est mesurée au sprint 1, avant toute modification.

| Métrique | Protocole | Ligne de base | Cible Phase 1 | Seuil de rattrapage |
|---|---|---|---|---|
| **SUS** | Questionnaire à 10 items, mêmes tâches, 8 à 12 répondants minimum (14 à 20 pour une comparaison rigoureuse). | Mesurée S1 | ≥ 80 | < 68 → revue de conception |
| **Temps par tâche** | Chronométrage des parcours UC1 à UC7, mêmes utilisateurs, même jeu de données. | Mesurée S1 | – 30 % | < – 15 % au jalon J2 |
| **Nombre de clics** | Comptage sur les mêmes parcours. | Mesurée S1 | – 30 % | < – 15 % |
| **SEQ** | Question unique de facilité perçue (7 points) posée après chaque tâche. | Mesurée S1 | ≥ 6,0 / 7 | < 5,0 sur une tâche → reprise de l'écran |
| **Onboarding autonome** | Un utilisateur non formé réalise UC1 et UC2 sans assistance. | — | Réussite | Échec → reprise des états vides et de l'aide contextuelle |

**Pourquoi mesurer avant de refondre.** Sans ligne de base au sprint 1, l'amélioration d'expérience ne pourra être ni prouvée ni contestée : elle restera une impression. C'est aussi la seule protection contre le risque R10, qui n'est pas de mal concevoir mais de ne pas s'en rendre compte à temps.

### 17.4 Conditions de mise en production

La mise en production commerciale de la Phase 1 est subordonnée à la réunion simultanée des cinq conditions suivantes. Aucune n'est négociable au motif que les autres sont satisfaites :

1. Les 52 critères d'acceptation de la section 13 passent en intégration continue.
2. Les douze barrières techniques de la section 17.2 sont au vert.
3. La validation écrite de l'expert-comptable membre de l'OECFM est obtenue sur les paramètres réglementaires et sur la structure des états financiers PCG 2005.
4. Une restauration de sauvegarde a été réalisée et vérifiée sur la pré-production.
5. Le score SUS atteint au minimum le seuil de rattrapage, et les écrans legacy du périmètre Phase 1 sont supprimés.

## 18. Annexes

Glossaire, références, suites

### 18.1 Glossaire

| Terme | Définition |
|---|---|
| **PCG 2005** | Plan Comptable Général malgache, adopté par le décret n° 2004-272 du 18 février 2004, cohérent avec les normes IAS/IFRS. Référentiel comptable applicable à Madagascar. |
| **SYSCOHADA révisé** | Référentiel comptable des États membres de l'OHADA. Ne s'applique pas à Madagascar, qui n'est pas membre de l'organisation. |
| **OHADA** | Organisation pour l'Harmonisation en Afrique du Droit des Affaires. Zone cible d'une phase ultérieure, Côte d'Ivoire en premier. |
| **OECFM** | Ordre des Experts-Comptables et Financiers de Madagascar. La validation d'un de ses membres conditionne la mise en production. |
| **IRSA** | Impôt sur les Revenus Salariaux et Assimilés (Madagascar). |
| **CNaPS** | Caisse Nationale de Prévoyance Sociale (Madagascar). |
| **OSTIE** | Organisation Sanitaire Tananarivienne Inter-Entreprises — organisme de médecine du travail. |
| **FMFP** | Fonds Malgache de Formation Professionnelle. |
| **SME** | Salaire Minimum d'Embauche. Sert de base au plafond des cotisations sociales (8 × SME). |
| **MGA** | Ariary malgache, devise de référence du produit. |
| **RLS** | Row Level Security — mécanisme PostgreSQL filtrant les lignes visibles au niveau de la base ; garde-fou de l'isolation multi-tenant. |
| **Strangler pattern** | Stratégie de refonte progressive : le nouveau système remplace l'ancien fonctionnalité par fonctionnalité, jusqu'à suppression complète du legacy. |
| **Chatter** | Fil unifié attaché à un objet : messages, notes internes, activités planifiées, abonnés, historique des transitions. |
| **Launchpad** | Page d'accueil composée de tuiles filtrées par rôle, favoris et documents récents. Inspirée de SAP Fiori. |
| **Function calling** | Mécanisme par lequel un modèle de langage propose l'appel d'une fonction déclarée ; dans WideHalo, la décision d'exécuter appartient au code, jamais au modèle. |
| **Text-to-SQL** | Génération de requêtes SQL par un modèle de langage. Interdit dans WideHalo par principe d'architecture. |
| **Jour-Token** | Unité d'estimation du volume de travail confié à un assistant IA agentique, exprimé en journées de session. Ne remplace pas le Jour-Homme : la supervision humaine est estimée séparément. |
| **SUS / SEQ** | System Usability Scale (questionnaire à 10 items) et Single Ease Question (question unique de facilité perçue à 7 points). |
| **FEFO** | First Expired, First Out — règle de sortie par péremption la plus proche. Notion agroalimentaire, Phase 3. |
| **CREDOC** | Crédit documentaire, instrument de paiement à l'importation. Notion textile, Phase 3. |
| **POS** | Point of Sale — point de vente. Désigne ici l'écran de caisse et l'ensemble session / ticket / règlement / clôture, pour la distribution comme pour les prestations de service. |
| **Session de caisse** | Période d'activité d'une caisse, ouverte avec un fond et close par un comptage. Unité de responsabilité du caissier et unité de génération de l'écriture comptable. |
| **Mobile money** | Monnaie électronique opérée par les opérateurs téléphoniques (Mvola, Orange Money, Airtel Money). Moyen de paiement de premier plan à Madagascar, traité comme un compte financier à part entière dans le plan de comptes. |
| **Hors ligne d'abord** | Conception dans laquelle l'écran fonctionne sans réseau par défaut et se synchronise ensuite, plutôt que de dégrader un fonctionnement connecté. |
| **Socle de simulation** | Modèle agrégé, daté et compact, extrait des données réelles, sur lequel le moteur de scénarios recalcule localement pour répondre en temps réel. |
| **DSO / DPO** | Délai moyen de règlement des clients et délai moyen de règlement des fournisseurs. Leviers majeurs de la projection de trésorerie. |
| **BFR** | Besoin en fonds de roulement — trésorerie immobilisée par le cycle d'exploitation (stocks + créances − dettes fournisseurs). |

### 18.2 Documents de référence

- Dépôt du produit : widehalo-web-python, branche madagascar1 — non audité lors de la rédaction (H1).
- INVENTAIRE_EXISTANT.md — à produire au sprint 1 ; devient le point de vérité sur l'existant et remplace les hypothèses de ce document.
- Plan Comptable Général 2005 — décret n° 2004-272 du 18 février 2004, Conseil Supérieur de la Comptabilité.
- Code général des impôts malgache et loi de finances en vigueur — pour les paramètres fiscaux, à confirmer par l'expert-comptable.
- Cahiers des charges des phases 2 et 3 — à produire, hors périmètre de ce document.

### 18.3 Suites immédiates

| Action | Échéance | Pourquoi elle passe avant le développement |
|---|---|---|
| **Produire INVENTAIRE_EXISTANT.md** | Sprint 1 | Toutes les hypothèses sur l'existant en dépendent ; un écart important sur le référentiel comptable modifierait l'ordonnancement du plan. |
| **Mesurer la ligne de base SUS et les temps par tâche** | Sprint 1 | Une fois la refonte commencée, la mesure de l'existant n'est plus possible — et l'amélioration devient indémontrable. |
| **Prendre contact avec l'expert-comptable OECFM** | Avant le sprint 16 | Sa disponibilité conditionne la mise en production ; l'engager tard expose au risque R2 sans marge de correction. |
| **Renommer intégralement ORION en WideHalo** | Sprint 1 | Décision de nommage actée ; plus le renommage tarde, plus il coûte cher en dépôts, conteneurs, variables et documentation. |
| **Rédiger les cahiers des charges des phases 2 et 3** | Après le jalon J2 | Les décisions d'architecture de la Phase 1 (moteur de vues, canal de notification, paramètres versionnés) doivent être éprouvées avant d'engager les phases suivantes. |

> Fin du cahier des charges WideHalo v3 — Phase 1. Ce document est destiné à être exploité directement en développement assisté : les critères d'acceptation de la section 13 sont écrits pour être traduits en tests, et le plan de la section 14 pour être suivi sprint par sprint. Les phases 2 (Patronnage, Strategy, Forecast, Business Intelligence, WhatsApp) et 3 (Achats/Import, Stock, Production, Qualité, Paie) feront l'objet de documents distincts.
