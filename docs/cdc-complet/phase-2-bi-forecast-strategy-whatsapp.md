# WideHalo v3 — Cahier des charges Phase 2

*Pilotage, prévision et restitution de l'ERP WideHalo*

**PHASE 2 — Business Intelligence • Forecast Strategy • WhatsApp**

| Rubrique | Valeur |
|---|---|
| PROJET | WideHalo — ERP PME |
| DOCUMENT | Cahier des charges |
| VERSION | 3.0 — Phase 2 |
| MAÎTRE D'OUVRAGE | Life MDG |
| PRÉREQUIS | Phase 1 en production |
| DATE | Septembre 2026 |
| MODE DE DÉVELOPPEMENT | Solo assisté IA (Claude Code) |
| DURÉE PHASE 2 | 22 sprints hebdomadaires |
| STATUT | Pour validation |

- **1. Résumé exécutif**
  - Les six décisions structurantes
  - Périmètre de ce document
- **2. Contexte, objectifs et périmètre**
  - 2.1 Ce dont la Phase 2 hérite
  - 2.2 Objectifs de la Phase 2
  - 2.3 Position dans la trajectoire produit
  - 2.4 Périmètre inclus
  - 2.5 Périmètre exclu
- **3. Utilisateurs cibles et cas d'usage**
  - 3.1 Parcours de référence de la Phase 2
  - 3.2 Ce qui change par rapport à la Phase 1
- **4. Contraintes du projet**
  - 4.1 Hypothèses ouvertes à lever
- **5. Architecture applicative**
  - 5.1 Couche présentation
  - 5.2 Couche logique métier
  - 5.3 Couche données
  - 5.4 Couche intégration
  - 5.5 Infrastructure
- **6. Sécurité**
  - 6.1 Le risque de fuite par agrégat
  - 6.2 Le canal sortant
  - 6.3 Intégrité des chiffres comme exigence de sécurité
- **7. UX/UI et confort d'usage**
  - 7.1 Composants à ajouter à la bibliothèque
  - 7.2 Performance de restitution sur réseau contraint
- **8. Gouvernance des données**
  - 8.1 Le dictionnaire d'indicateurs
  - 8.2 Classification des données ajoutées
  - 8.3 Rétention
  - 8.4 Qualité et réconciliation
- **9. Interopérabilité et outils tiers**
  - 9.1 Règles imposées par le fournisseur
  - 9.2 Choix du mode de raccordement
- **10. Scalabilité**
  - 10.1 Budgets d'architecture révisés
- **11. Choix technologiques**
  - 11.1 Entrepôt analytique
  - 11.2 Outil de restitution
  - 11.3 Moteur de prévision
  - 11.4 Briques confirmées sans réexamen
- **12. Socle analytique et couche sémantique**
  - 12.1 Entrepôt en étoile
  - 12.2 Rafraîchissement
  - 12.3 Couche sémantique et moteur de requête guidé
- **13. Spécifications fonctionnelles — Phase 2**
  - 13.1 Module Business Intelligence
  - 13.2 Module Forecast
  - 13.3 Module Strategy
  - 13.4 Module WhatsApp
- **14. Plan de développement — sprints hebdomadaires**
  - 14.1 Ordonnancement et dépendances
  - 14.2 Bloc A — Cadrage et socle analytique (S1 à S5)
  - 14.3 Bloc B — Business Intelligence (S6 à S9)
  - 14.4 Bloc C — Forecast (S10 à S13)
  - 14.5 Bloc D — Strategy (S14 à S17)
  - 14.6 Bloc E — WhatsApp (S18 à S21)
  - 14.7 Bloc F — Durcissement et mise en production (S22)
  - 14.8 Répartition du travail humain / assistant IA
- **15. Estimation détaillée**
  - 15.1 Hypothèses de l'estimation
  - 15.2 Synthèse par bloc
  - 15.3 Comparaison avec la Phase 1
  - 15.4 Trois scénarios
  - 15.5 Marges appliquées par type de tâche
- **16. Risques et plan de mitigation**
- **17. Critères de recette et métriques de succès**
  - 17.1 Recette fonctionnelle
  - 17.2 Recette technique — barrières bloquantes
  - 17.3 Métriques de succès
  - 17.4 Conditions de mise en production
- **18. Annexes**
  - 18.1 Glossaire — termes propres à la Phase 2
  - 18.2 Documents de référence
  - 18.3 Suites immédiates

## 1. Résumé exécutif

Ce qu'il faut retenir en une page

La Phase 1 a rendu WideHalo **utilisable** : la chaîne commerciale et comptable, l'encaissement au comptoir, le patronnage et un copilote. La Phase 2 le rend **pilotable** : elle transforme les données accumulées en décisions, et ouvre le canal par lequel ces décisions atteignent les clients.

Quatre modules qui forment un enchaînement, non un catalogue : la Business Intelligence produit les chiffres, Forecast les projette, Strategy les confronte à une intention, WhatsApp les diffuse. Chacun dépend du précédent, ce qui explique l'ordre du plan de développement.

## 54,5

### Les six décisions structurantes

1. **Un indicateur, une définition, dans tout le produit.** La Phase 2 introduit un dictionnaire d'indicateurs gouverné : chaque mesure porte un nom, une formule, un propriétaire, ses axes d'analyse autorisés et une version. Rapports, tableaux de bord, prévisions et budgets s'y adossent tous. C'est la seule protection contre le défaut qui tue un module décisionnel : trois chiffres d'affaires différents sur trois écrans.
2. **Pas de second moteur de base de données.** L'entrepôt analytique est un schéma en étoile dans le PostgreSQL existant, avec agrégats matérialisés et rafraîchissement incrémental. Un moteur analytique dédié ajouterait un composant à exploiter pour un gain que le volume ne justifie pas encore.
3. **Le self-service se fait sans SQL libre.** Le constructeur de rapports manipule des mesures et des dimensions déclarées, jamais du SQL. C'est le prolongement direct de l'interdiction du text-to-SQL posée en Phase 1 : l'utilisateur compose librement dans un vocabulaire, et le copilote hérite gratuitement d'un moyen sûr d'interroger les données.
4. **La prévision publie son erreur.** Le modèle naïf saisonnier est toujours calculé comme étalon, l'erreur est mesurée par rétrotest glissant et affichée en clair, et l'ajustement humain est autorisé, tracé et évalué. Une prévision dont on cache l'erreur est abandonnée au premier écart constaté.
5. **WhatsApp est un adaptateur, pas une refonte.** Le moteur de notification abstrait livré en Phase 1 (destinataire, gabarit, canal, statut, réessai) accueille le canal comme un adaptateur supplémentaire. L'ERP reste intégralement fonctionnel sans lui : c'est un canal de confort, jamais un chemin critique.
6. **La prévision d'approvisionnement n'est pas livrable en Phase 2.** Elle suppose les modules Stock, Achats et Production, qui relèvent de la Phase 3. Le périmètre de Forecast est donc borné aux ventes, aux encaissements et à la trésorerie. Ce point doit être écrit dans l'offre commerciale, pas découvert en cours de projet.

### Périmètre de ce document

Ce document couvre **exclusivement la Phase 2**. Il suppose la Phase 1 livrée et stabilisée : le socle d'expérience utilisateur, le référentiel comptable PCG 2005, les paramètres réglementaires versionnés, le moteur de vues, le moteur de notification, la simulation financière et le gateway IA sont des acquis et ne sont pas respécifiés ici. La Phase 3 (Achats/Import et CREDOC, Stock, Production, Qualité/HACCP, Paie) fera l'objet d'un document distinct.

**Condition de démarrage.** La Phase 2 ne doit pas être lancée avant que la Phase 1 ne soit en production et stabilisée — flux de support redescendu, écrans legacy supprimés. Un module décisionnel construit sur des données opérationnelles encore instables produit des chiffres faux, et un chiffre faux affiché une fois en comité de direction coûte des mois de crédibilité. Cette condition compte davantage que la date de démarrage.

## 2. Contexte, objectifs et périmètre

Ce que la Phase 1 a rendu possible, et ce que la Phase 3 conditionne encore

### 2.1 Ce dont la Phase 2 hérite

La Phase 2 n'est pas un nouveau projet : c'est l'exploitation d'un socle. Six acquis de la Phase 1 sont directement réutilisés, et le coût de la Phase 2 n'est tenable que parce qu'ils existent.

| Acquis Phase 1 | Usage en Phase 2 |
|---|---|
| **Bibliothèque de composants et moteur de vues** | Les tableaux de bord et le constructeur de rapports réutilisent le data grid, le tableau croisé et les filtres sauvegardés. Aucun écran de restitution n'est construit de zéro : neuf composants nouveaux suffisent. |
| **Moteur de notification abstrait** | WhatsApp devient un adaptateur de canal. C'est la décision de Phase 1 qui rend le bloc WhatsApp court plutôt que structurant. |
| **Socle de simulation financière** | Forecast et Strategy s'y branchent : la prévision publiée devient le scénario de référence, et un budget peut être initialisé depuis un scénario. |
| **Gateway IA à outils en lecture seule** | Le copilote gagne des outils analytiques, sans changer de principe : liste blanche, lecture seule, aucun SQL généré. |
| **Permissions par rôle et journal d'audit** | Appliqués à la restitution et à la diffusion, y compris sur les données agrégées — point traité en section 6.1. |
| **Paramètres versionnés (core_regulatory_parameter)** | Accueille le calendrier des jours ouvrés et fériés malgaches utilisé par la prévision, ainsi que les catégories et coûts de message du canal. |

### 2.2 Objectifs de la Phase 2

| Objectif | Énoncé | Comment il est mesuré |
|---|---|---|
| **O1 — Cohérence** | Qu'un même indicateur affiche la même valeur partout, quel que soit l'écran, le rapport ou le canal. | Zéro divergence sur un jeu d'indicateurs témoins, vérifié en intégration continue, et rapprochement des rapports financiers aux états PCG 2005. |
| **O2 — Autonomie de restitution** | Qu'un utilisateur métier obtienne une réponse chiffrée sans passer par l'éditeur. | Part des rapports consultés issus du constructeur self-service ; baisse du nombre de demandes de rapport adressées au support. |
| **O3 — Prévision crédible** | Que la prévision batte un étalon naïf et que son erreur soit connue de ceux qui l'utilisent. | Erreur pondérée sous le seuil par famille ; part des séries battant l'étalon naïf ; erreur affichée sur chaque série. |
| **O4 — Pilotage réel** | Que la revue de direction se prépare dans l'outil et non dans un tableur repris à la main chaque mois. | Temps de préparation du pack de revue réduit de moitié ; pack généré et figé depuis WideHalo. |
| **O5 — Canal effectif** | Que les documents et relances atteignent réellement le destinataire, sur le canal qu'il utilise. | Taux de livraison et de lecture comparé à l'e-mail ; effet mesuré sur le délai moyen de règlement après relance. |
| **O6 — Maîtrise du coût variable** | Que le premier coût variable du produit reste sous contrôle technique, pas seulement contractuel. | Plafond mensuel par tenant respecté ; aucun dépassement non alerté. |

### 2.3 Position dans la trajectoire produit

| Phase | Modules | Rôle | Statut |
|---|---|---|---|
| **Phase 1** | Socle UX + CRM + Sales + Accounting (PCG 2005) + POS + Simulation financière + Patronnage + IA | Rendre le produit utilisable et conforme. Chaîne commerciale et comptable, encaissement, patronnage. | Prérequis — doit être en production |
| **Phase 2** | Business Intelligence + Forecast + Strategy + WhatsApp | Rendre le produit pilotable et communicant : restituer juste, anticiper avec une erreur mesurée, confronter à une intention, diffuser. | Objet de ce document |
| **Phase 3** | Achats/Import et CREDOC, Stock et entrepôt, Production, Qualité/HACCP, Paie | Couverture ERP complète des deux verticales. Étend Forecast à la prévision de besoins matière et de charge d'atelier. | Cahier des charges séparé |

### 2.4 Périmètre inclus

- **Socle analytique** : entrepôt en étoile dans PostgreSQL, dimensions conformes, faits à la ligne de document, rafraîchissement incrémental et son journal, agrégats matérialisés, couche sémantique et dictionnaire d'indicateurs, moteur de requête guidé.
- **Module Business Intelligence** : catalogue de rapports rationalisé et industrialisé sur la couche sémantique, constructeur self-service, tableaux de bord composables par rôle, exploration du détail depuis un agrégé, diffusion planifiée, exports asynchrones, écran de gouvernance du dictionnaire.
- **Module Forecast** : préparation des séries, calendrier malgache paramétré, méthodes statistiques avec sélection par rétrotest, erreur publiée, prévision de ventes collaborative avec ajustement tracé et évalué, prévision d'encaissement et trésorerie à douze mois.
- **Module Strategy** : objectifs et résultats clés en cascade adossés au dictionnaire, initiatives, budget avec versions et verrouillage, suivi réel / budget / prévision avec commentaire de gestion, pack de revue figé, cartographie des risques d'entreprise.
- **Module WhatsApp** : adaptateur de canal, bibliothèque de modèles approuvés, gestion du consentement, conversation intégrée au chatter, envois transactionnels, parcours entrant borné à un menu d'intentions, journal d'envoi et de coût, plafonnement.
- **Extension du copilote** : outils analytiques en lecture seule sur la couche sémantique.

### 2.5 Périmètre exclu

- Modules Achats/Import et CREDOC, Stock et entrepôt, Production, Qualité/HACCP, Paie (→ Phase 3).
- Prévision de besoins matière et de charge d'atelier : dépend du Stock et de la Production. Voir l'encadré ci-dessous.
- Apprentissage automatique avancé sur la prévision : la Phase 2 s'en tient à des méthodes interprétables, adaptées à la profondeur d'historique disponible.
- SQL libre pour l'utilisateur final et accès direct à l'entrepôt par un outil tiers : exclus par principe, comme le text-to-SQL en Phase 1.
- Agent conversationnel génératif libre sur le canal de messagerie : le parcours entrant est borné à un menu d'intentions déclarées.
- Paiement par le canal de messagerie et catalogue de vente intégré au canal.
- Consolidation multi-sociétés et reporting de groupe.
- Suivi budgétaire engagé (engagements, réservations de crédit) : la Phase 2 compare réel, budget et prévision, sans gestion d'engagement.

**Forecast est volontairement amputé en Phase 2, et c'est un choix de séquence.** Une prévision de besoins matière suppose de connaître les stocks, les délais d'approvisionnement et les nomenclatures ; une prévision de charge d'atelier suppose les ordres de fabrication. Ces données arrivent en Phase 3. Deux options se présentaient : décaler Forecast après la Phase 3, ou livrer dès maintenant la partie qui repose sur des données déjà disponibles — ventes, encaissements, trésorerie. La seconde a été retenue : c'est celle qui intéresse le dirigeant, et le modèle dimensionnel construit ici accueillera les faits de la Phase 3 sans reprise. La contrepartie est une exigence de franchise commerciale : ne pas vendre « la prévision » sans dire ce qu'elle ne couvre pas encore.

## 3. Utilisateurs cibles et cas d'usage

Des utilisateurs moins nombreux, mais à fort pouvoir de décision

La Phase 2 change de public. Là où la Phase 1 servait des utilisateurs intensifs (commercial, comptable, caissier), la Phase 2 sert surtout des utilisateurs occasionnels mais décisionnaires. Cela déplace l'exigence : ils ne prendront pas le temps d'apprendre l'outil, et une seule valeur fausse suffit à leur faire perdre confiance dans l'ensemble.

| Persona | Contexte d'usage réel | Attentes prioritaires Phase 2 | Écrans concernés |
|---|---|---|---|
| **Dirigeant PME** **Déjà utilisateur en Phase 1, usage élargi** | Consulte quelques minutes par jour, prépare une revue mensuelle, arbitre sous contrainte de temps. Souvent en déplacement. | Un tableau de bord qui dit l'essentiel sans clic, une prévision dont il comprend la fiabilité, et un pack de revue qu'il n'a pas à refaire à la main. | Tableau de bord de direction, pack de revue, prévision, objectifs. |
| **Contrôleur de gestion** **Utilisateur central de la Phase 2** | Construit le budget, analyse les écarts, produit les rapports que les autres consomment. Aujourd'hui dans un tableur, avec des reprises manuelles mensuelles. | Construire un rapport sans demander l'éditeur ; connaître la définition exacte de chaque indicateur ; expliquer un écart en descendant jusqu'à la pièce. | Constructeur de rapports, budget, suivi des écarts, dictionnaire. |
| **Responsable commercial** **Contributeur à la prévision** | Connaissance terrain que la statistique ignore : appel d'offres en cours, client qui ferme, collection qui démarre. | Pouvoir corriger une prévision statistique et voir son apport mesuré, plutôt que subir un chiffre imposé par un modèle. | Prévision collaborative, objectifs d'équipe. |
| **Comptable** **Garant de la cohérence** | Sera le premier à repérer une divergence entre un rapport et la comptabilité, et le premier à la signaler. | Que les rapports se rapprochent à l'ariary près des états comptables, et que la définition de chaque indicateur soit écrite. | Rapports financiers, dictionnaire, rapprochements. |
| **Client ou fournisseur** **Destinataire, non-utilisateur** | Reçoit des messages, souvent sur un téléphone d'entrée de gamme, avec un forfait données limité. | Recevoir un document lisible, pouvoir répondre, et pouvoir se désabonner sans démarche compliquée. | Messages sortants, parcours entrant, consentement. |
| **Administrateur fonctionnel** | Configure le canal, les rôles et les tableaux de bord au démarrage, puis ponctuellement. | Voir et plafonner le coût du canal, savoir quelles données sortent du serveur, composer les tuiles par rôle. | Configuration du canal, gouvernance, droits, launchpad. |

### 3.1 Parcours de référence de la Phase 2

La numérotation prolonge celle de la Phase 1 (UC1 à UC8). Ces six parcours servent de tâches de référence pour les mesures de la section 17. Portant sur des modules nouveaux, leur ligne de base est la pratique actuelle hors ERP — tableur, reprises manuelles, appels téléphoniques — mesurée au sprint 1.

| Réf. | Parcours de référence | Acteur | Définition de fin |
|---|---|---|---|
| **UC9** | Construire un rapport croisé inédit sans assistance de l'éditeur | Contrôleur de gestion | Rapport enregistré, partagé, avec la définition de ses indicateurs consultable. |
| **UC10** | Expliquer un écart de marge en descendant jusqu'aux pièces | Contrôleur de gestion | Chemin complet de l'agrégé au détail, sans export intermédiaire. |
| **UC11** | Ajuster la prévision de ventes d'une famille et justifier l'écart | Responsable commercial | Ajustement enregistré, tracé avec motif, comparé à la prévision statistique. |
| **UC12** | Construire le budget de l'exercice à partir d'un scénario de simulation | Contrôleur de gestion | Budget versionné et verrouillé, avec la référence du scénario source conservée. |
| **UC13** | Préparer et figer le pack de revue mensuelle de direction | Dirigeant | Pack généré, horodaté, immuable, diffusé aux participants. |
| **UC14** | Relancer un client sur une échéance échue via le canal de messagerie | Commercial ou comptable | Message envoyé depuis un modèle approuvé, tracé dans le chatter, avec statut de livraison et coût imputé. |

### 3.2 Ce qui change par rapport à la Phase 1

- **La justesse compte plus que la vitesse.** Un caissier tolère une seconde d'attente, pas une erreur de rendu de monnaie ; un dirigeant tolère trois secondes de chargement, pas un chiffre faux en réunion. L'arbitrage entre performance et exactitude ne se fait pas dans le même sens qu'en Phase 1.
- **L'usage est occasionnel, donc l'écran doit être auto-explicatif.** Un utilisateur qui revient une fois par mois a tout oublié. La définition d'un indicateur doit être accessible au survol, pas dans une documentation.
- **Une partie des destinataires n'est pas utilisatrice.** Les messages sortent du périmètre de l'application : la qualité de rédaction et le respect du consentement engagent l'image du client de WideHalo, pas seulement la nôtre.
- **Le produit acquiert un coût variable.** Jusqu'ici, servir un client de plus ne coûtait rien de marginal. Chaque message sortant a un prix : cela change le modèle économique et impose un plafonnement technique, pas seulement contractuel.
- **L'adoption devient un critère, pas une espérance.** Une facture doit être émise, une caisse doit être tenue : leur usage est imposé par le processus. Un tableau de bord n'est ouvert que s'il est utile — d'où la mesure d'adoption de la section 17.

## 4. Contraintes du projet

Ce qui est imposé et non négociable

| Catégorie | Contrainte | Conséquence sur la conception |
|---|---|---|
| **Prérequis** | La Phase 1 doit être en production et stabilisée. Les modules Stock, Achats et Production ne le sont pas. | Le périmètre de Forecast est borné. L'entrepôt est conçu pour accueillir les faits de la Phase 3 sans reprise du modèle dimensionnel. |
| **Organisationnelle** | Toujours un seul développeur, qui assure désormais aussi le support d'un produit en production. | La capacité hebdomadaire disponible est plus faible qu'en Phase 1 : l'estimation retient 4,5 jours effectifs par semaine au lieu de 5. |
| **Technique imposée** | Même pile, même instance PostgreSQL, même bibliothèque de composants. Aucun nouveau composant d'infrastructure sans justification forte. | Entrepôt analytique dans la base existante ; construction de la restitution sur le socle Phase 1 plutôt qu'intégration d'un outil de BI tiers. |
| **Données personnelles** | Le canal de messagerie fait sortir des données identifiantes (numéro, nom, montant dû) vers un tiers établi hors de Madagascar. | Consentement explicite et révocable, minimisation du contenu, registre des traitements, information contractuelle du client. Le canal est désactivé par défaut. |
| **Coût variable** | Les messages sortants sont facturables et le modèle tarifaire du fournisseur évolue. | Plafond mensuel par tenant appliqué techniquement, avec arrêt automatique des envois non critiques et alerte préalable. Catégories et coûts paramétrés, jamais codés. |
| **Dépendance administrative** | Un numéro et un compte professionnels doivent être vérifiés par le fournisseur avant tout envoi. Le délai n'est pas maîtrisé par l'éditeur. | La démarche est engagée au sprint 14, quatre sprints avant le besoin. L'e-mail reste le canal par défaut, ce qui évite qu'un blocage administratif ne bloque la Phase 2. |
| **Produit** | Budgets d'architecture toujours vérifiés en intégration continue. | Rehaussés en section 10, pas contournés. Les tables analytiques comptent dans le budget de modèles, et un budget de rapports est introduit. |
| **Délai** | 22 sprints hebdomadaires. | Le bloc BI est placé avant Forecast et Strategy parce que les deux en dépendent. Seul le bloc WhatsApp est déplaçable dans le calendrier. |

### 4.1 Hypothèses ouvertes à lever

La numérotation prolonge celle de la Phase 1 (H1 à H5). Chaque hypothèse a un sprint de levée assigné ; une hypothèse non levée à la date prévue devient un risque actif et remonte en revue de sprint.

| Réf. | Hypothèse posée | Levée prévue |
|---|---|---|
| **H6** | Le catalogue de rapports existant est exploitable en l'état comme spécification. Son contenu réel, sa redondance et sa cohérence n'ont pas été audités. | Sprint 1 — audit du catalogue et rationalisation assumée : mieux vaut porter 40 rapports justes que 91 rapports hétérogènes. |
| **H7** | Le volume analytique reste dans les capacités d'un PostgreSQL unique sur le serveur de production, avec agrégats matérialisés et partitionnement. | Sprint 2 — banc d'essai sur un jeu simulé à trois exercices. Déclenche, si nécessaire, le recours à un moteur analytique embarqué. |
| **H8** | Les règles et la tarification de la plateforme de messagerie professionnelle (catégories, fenêtre de service, approbation des modèles, mode de facturation) sont celles connues à la rédaction. Elles évoluent fréquemment. | Sprint 18 — vérification directe de la documentation du fournisseur avant tout code. Aucune règle tarifaire n'est écrite dans le code. |
| **H9** | Un numéro et un compte professionnels vérifiables sont disponibles pour le tenant pilote dans les délais du projet. | Sprint 18 — démarche administrative engagée dès le sprint 14. Repli identifié sur un intermédiaire spécialisé (section 9.2). |
| **H10** | La profondeur d'historique disponible à l'issue de la Phase 1 permet de détecter une saisonnalité fiable (au minimum deux cycles annuels complets). | Sprint 10 — diagnostic sur données réelles. Si l'historique est insuffisant, la prévision est livrée sans composante saisonnière et l'écran le dit. |
| **H11** | La capacité hebdomadaire du développeur reste de 4,5 jours effectifs malgré le support d'un produit en production, et les ratios de gain IA de la Phase 1 restent valables sur un profil de tâches plus orienté modélisation. | Sprint 5 — mesure réelle et recalibrage du reste du plan. |

**H6 mérite une décision plutôt qu'une levée.** Un catalogue de rapports hérité est presque toujours le résultat d'une accumulation : des rapports qui se recoupent, d'autres que personne n'ouvre, quelques-uns qui contredisent les autres. Les porter tels quels sur la couche sémantique reviendrait à industrialiser l'incohérence. Le sprint 1 doit donc produire un arbitrage explicite — conserver, fusionner, remplacer par un rapport paramétrable, ou supprimer — et le nombre final peut légitimement être inférieur à la moitié. Ce nombre devient ensuite un budget vérifié en intégration continue, pour que le catalogue ne recommence pas à gonfler.

## 5. Architecture applicative

Trois ajouts à une architecture inchangée

La Phase 2 n'introduit aucun nouveau composant d'infrastructure. Elle ajoute trois briques à l'intérieur du monolithe modulaire existant : une couche analytique (entrepôt et rafraîchissement), une couche sémantique (dictionnaire d'indicateurs et moteur de requête guidé) et un service de prévision. Le canal WhatsApp est un adaptateur du moteur de notification déjà livré. C'est le bénéfice concret des décisions d'abstraction prises en Phase 1 : ce qui aurait été une refonte devient un ajout.

****Chaîne analytique — Phase 2****

```
┌──────────────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ SOURCES OPÉRATIONNELLES (Phase 1, inchangées)                  │  │
│  │   CRM · Sales · Accounting · POS · Patronnage                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ RAFRAÎCHISSEMENT INCRÉMENTAL (worker planifié)                 │  │
│  │   détection des lignes modifiées · chargement · agrégats       │  │
│  │   journal de rafraîchissement visible à l'utilisateur          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ ENTREPÔT EN ÉTOILE (même PostgreSQL)                           │  │
│  │   dimensions conformes : temps · tiers · article · point de    │  │
│  │   vente · compte · collection · utilisateur                    │  │
│  │   faits : ventes · encaissements · écritures · tickets POS     │  │
│  │           prévisions · budget                                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                 ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ COUCHE SÉMANTIQUE — pièce maîtresse de la Phase 2              │  │
│  │   dictionnaire d'indicateurs : nom · définition · formule      │  │
│  │                               propriétaire · axes · version    │  │
│  │   moteur de requête guidé : mesures et dimensions DÉCLARÉES    │  │
│  │   AUCUN SQL libre exposé                                       │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
Trois consommateurs, un seul vocabulaire :
        ▼                    ▼                      ▼
  BUSINESS             FORECAST               STRATEGY
  INTELLIGENCE         prévisions issues      budget · objectifs
  rapports · tableaux  des mêmes séries       écarts calculés sur
  de bord                                     les mêmes définitions
→ WHATSAPP : adaptateur du moteur de notification de la Phase 1
→ COPILOTE : outils lecture seule sur la couche sémantique
```

### 5.1 Couche présentation

Inchangée dans ses principes : rendu serveur, fragments HTMX, Alpine pour l'état d'interface, composants django-cotton. Trois extensions seulement :

- **Tableaux de bord composables** : une grille de tuiles positionnables par rôle, chaque tuile chargeant son fragment indépendamment. Un tableau de bord lent doit dégrader tuile par tuile, jamais bloquer la page entière.
- **Constructeur de rapports** : manipulation de mesures et de dimensions déclarées, avec aperçu progressif. C'est le seul écran de la Phase 2 qui demande une véritable interactivité locale.
- **Éditeur de prévision** : courbe combinant historique, prévision statistique et ajustement, avec saisie directe sur la période. Recalcul local sur un modèle compact, selon le même principe que le socle de simulation de la Phase 1.

### 5.2 Couche logique métier

Trois nouveaux modules Django (BI, Forecast, Strategy) et un adaptateur de canal, communiquant avec l'existant par services explicites. La règle de la Phase 1 tient : aucun module n'accède directement aux modèles d'un autre.

Le service de prévision est le seul traitement réellement coûteux en calcul de la Phase 2. Il s'exécute exclusivement en asynchrone, sur le worker, sur des séries pré-agrégées issues de l'entrepôt — jamais sur les tables opérationnelles, et jamais dans le cycle d'une requête utilisateur. Une prévision est un résultat publié, pas un calcul à la demande.

Le rafraîchissement analytique est planifié (nocturne par défaut) et déclenchable manuellement. Il est incrémental : il ne recharge que ce qui a changé. Son état est une donnée affichée à l'utilisateur, pas un détail technique — un tableau de bord dont on ignore l'heure de fraîcheur est un tableau de bord dont on ignore la validité.

### 5.3 Couche données

Même instance PostgreSQL, même isolation par discriminant et RLS. L'entrepôt est un schéma séparé dans la même base, ce qui permet des droits distincts et un jeu d'index différent sans ajouter un composant à exploiter.

| Élément | Décision Phase 2 |
|---|---|
| **Modèle** | Schéma en étoile, dimensions conformes partagées par tous les faits. C'est ce qui permettra d'ajouter les faits de stock et de production en Phase 3 sans reprise. |
| **Granularité** | Les faits sont stockés à la ligne de document, pas à l'agrégé : c'est la condition de l'exploration jusqu'à la pièce (BI-10). |
| **Agrégats** | Vues matérialisées pour les combinaisons les plus consultées, rafraîchies avec l'entrepôt. Ce sont elles qui tiennent l'objectif de 3 secondes. |
| **Partitionnement** | Faits partitionnés par exercice, ce qui borne le coût des requêtes à périmètre récent et permet d'archiver un exercice sans toucher au reste. |
| **Isolation** | Le tenant_id est porté par tous les faits et toutes les dimensions non partagées ; les policies RLS s'appliquent à l'entrepôt comme à l'opérationnel, sans exception. |
| **Rejeu** | Un chargement doit être rejouable à l'identique sur une période donnée sans produire de doublon : condition de correction d'un incident sans repartir de zéro. |

### 5.4 Couche intégration

- **Sortant — canal de messagerie** : appels HTTPS vers l'interface de programmation du fournisseur, bornés par un délai maximal, réessayés avec espacement croissant, protégés par un disjoncteur. Les envois passent par la file du moteur de notification, jamais en direct depuis une vue.
- **Entrant — réception de messages** : point de terminaison dédié, signature du fournisseur vérifiée systématiquement, traitement asynchrone. Un message entrant est une donnée non fiable : il est traité comme tel.
- **Outils analytiques du copilote** : nouveaux outils en lecture seule sur la couche sémantique. Ils ne reçoivent pas d'accès à l'entrepôt mais aux indicateurs déclarés, avec les mêmes restrictions de rôle et de tenant que l'interface.
- **Sortie de rapports** : exports asynchrones et diffusion planifiée, par e-mail puis par le canal de messagerie. Un export volumineux ne bloque jamais l'interface.

### 5.5 Infrastructure

Aucun conteneur supplémentaire. Deux ajustements de dimensionnement : le worker devient significativement plus sollicité (rafraîchissement nocturne, prévisions, exports, envois), ce qui justifie de le dédoubler en deux files — une pour les tâches longues planifiées, une pour les tâches courtes interactives, afin qu'un rafraîchissement de deux heures ne retarde pas l'envoi d'une facture. Et la fenêtre de rafraîchissement devient une contrainte d'exploitation à surveiller, au même titre que la mémoire d'Ollama en Phase 1.

## 6. Sécurité

Deux surfaces nouvelles : l'agrégat et le canal sortant

Les fondations de la Phase 1 sont inchangées : authentification, second facteur pour les rôles sensibles, RLS avec rôle applicatif non superutilisateur, journal d'audit, confinement du copilote. La Phase 2 ouvre deux surfaces qui n'existaient pas.

### 6.1 Le risque de fuite par agrégat

Un module décisionnel crée une voie de contournement subtile des permissions : un utilisateur qui n'a pas accès aux salaires individuels peut déduire une rémunération d'un agrégat filtré sur une seule personne. Un commercial qui ne voit que son portefeuille peut en déduire le chiffre d'affaires total si un rapport lui donne le cumul.

- Les droits s'appliquent à la restitution, pas seulement à l'écran de liste : le moteur de requête applique le périmètre du rôle **avant** l'agrégation, jamais après.
- Chaque indicateur du dictionnaire déclare les rôles autorisés et les axes d'analyse permis : un indicateur peut être consultable au global et interdit à la maille individuelle.
- Les tests de recette vérifient, rôle par rôle, qu'aucun rapport ne restitue plus que ce que l'utilisateur verrait en détail (BI-6).
- L'exploration du détail depuis un agrégé (BI-10) est bornée par les mêmes droits : un chiffre peut être visible sans que ses lignes le soient, et l'interface le dit.

### 6.2 Le canal sortant

| Risque | Spécificité Phase 2 | Contre-mesure |
|---|---|---|
| **Envoi non consenti** | Une erreur de configuration ou un import de contacts mal contrôlé peut déclencher des envois de masse à des destinataires qui n'ont rien demandé. | Le consentement est une condition vérifiée au moment de l'envoi, pas à la configuration. Un destinataire sans consentement enregistré ne reçoit rien, quelle que soit l'origine de la demande d'envoi (WA-1). |
| **Fuite de données personnelles** | Nom, numéro, montant dû et référence de document sortent vers un tiers établi hors de Madagascar. | Minimisation du contenu des modèles : n'envoyer que ce qui est nécessaire, privilégier un lien sécurisé à durée limitée plutôt que le détail dans le message. Écran de configuration énonçant explicitement ce qui sort (WA-10). |
| **Injection par message entrant** | Le contenu d'un message reçu peut contenir des instructions destinées au copilote, ou du balisage destiné à l'interface qui l'affichera. | Échappement systématique à l'affichage ; parcours entrant borné à un menu d'intentions déclarées, sans génération libre (WA-8) ; le copilote ne dispose d'aucun outil d'écriture. |
| **Usurpation du point d'entrée** | Le point de terminaison de réception est public par nature. | Vérification systématique de la signature du fournisseur ; rejet silencieux et journalisé de toute requête non signée ; limitation de débit. |
| **Détournement économique** | Un envoi en boucle, provoqué par un défaut ou volontairement, se traduit directement en coût. | Plafond mensuel par tenant appliqué techniquement, arrêt automatique des envois non critiques, alerte avant seuil, limite de fréquence par destinataire (WA-5). |
| **Compromission des jetons du canal** | Un jeton d'accès volé permet d'envoyer au nom du client. | Jetons en variables d'environnement, jamais en base ni en dépôt ; rotation documentée ; portée minimale ; journalisation de tout envoi avec son origine applicative. |

### 6.3 Intégrité des chiffres comme exigence de sécurité

Un point souvent traité comme un enjeu fonctionnel relève en réalité de la sécurité : l'altération silencieuse d'une définition d'indicateur. Modifier la formule du taux de marge change rétroactivement tous les rapports, tous les écarts budgétaires et toutes les prévisions qui s'y adossent — sans qu'aucune donnée n'ait été touchée. Toute modification de définition crée donc une version, conserve la précédente, signale les rapports impactés et apparaît au journal d'audit (BI-9). Les packs de revue déjà figés conservent la définition en vigueur à leur génération.

## 7. UX/UI et confort d'usage

Concevoir pour un utilisateur qui revient une fois par mois

Les sept principes de la Phase 1 s'appliquent sans changement. La Phase 2 en ajoute quatre, propres à la restitution décisionnelle, où le risque n'est pas la lenteur mais l'interprétation fausse d'un chiffre juste.

| Principe | Énoncé | Critère de vérification |
|---|---|---|
| **P8 — Tout chiffre est explicable** | La définition d'un indicateur est accessible sans quitter l'écran, et son détail est atteignable en un clic. | Chaque valeur agrégée expose sa définition au survol et permet d'atteindre ses lignes sources (BI-10). |
| **P9 — Tout chiffre est daté** | L'utilisateur sait toujours de quand datent les données qu'il regarde et sur quel périmètre elles portent. | Chaque tableau de bord affiche l'heure du dernier rafraîchissement et son état, échec compris (BI-4). |
| **P10 — L'incertitude est montrée** | Une prévision n'est jamais présentée comme un fait : son erreur passée et son intervalle accompagnent la valeur. | Chaque série prévisionnelle affiche son erreur mesurée et sa comparaison à la référence naïve (FOR-1, FOR-2). |
| **P11 — Le figé reste figé** | Un document de décision (pack de revue, budget verrouillé) n'évolue plus après sa génération. | Un pack réouvert un mois plus tard affiche exactement les mêmes valeurs (STR-7). |

### 7.1 Composants à ajouter à la bibliothèque

Neuf composants seulement : c'est la mesure du rendement de l'investissement de la Phase 1. Le data grid, le tableau croisé, la barre de filtres, le chatter, les formulaires et la palette de commandes sont réutilisés tels quels.

| Composant | Spécification | Sprint |
|---|---|---|
| **c-dashboard-grid** | Grille de tuiles positionnables et redimensionnables, composition par rôle, chargement indépendant et dégradation tuile par tuile. | 5 |
| **c-chart** | Graphiques (courbe, barres, empilé, combiné) rendus légers, avec valeurs accessibles en texte pour l'accessibilité et l'export. | 5 |
| **c-metric-value** | Valeur d'indicateur avec sa définition au survol, sa date de fraîcheur et son accès au détail. Rend la gouvernance visible plutôt que documentaire. | 3 |
| **c-report-builder** | Sélection de mesures et de dimensions déclarées, filtres, tri, aperçu progressif, enregistrement et partage. Aucun champ de saisie libre de requête. | 7 |
| **c-refresh-badge** | État du rafraîchissement : dernière exécution, durée, volume, échec éventuel, déclenchement manuel si le rôle l'autorise. | 2 |
| **c-forecast-editor** | Courbe historique + prévision + ajustement, saisie directe par période, motif obligatoire, comparaison permanente à la statistique. | 12 |
| **c-variance-table** | Tableau réel / budget / prévision avec écart en valeur et en pourcentage, seuil d'alerte, et champ de commentaire de gestion rattaché à la ligne. | 16 |
| **c-okr-card** | Objectif, résultats clés, indicateur adossé, avancement, contribution au niveau supérieur. | 14 |
| **c-conversation** | Fil de messages entrants et sortants avec statut de livraison, modèle utilisé, fenêtre de service restante et coût imputé. Intégré au chatter. | 19 |

### 7.2 Performance de restitution sur réseau contraint

- Objectif de **3 secondes par tableau de bord** sur profil réseau dégradé, quelle que soit la profondeur d'historique. Il est tenu par les agrégats matérialisés, pas par l'optimisation de requêtes à la volée.
- **Chargement par tuile** : chaque tuile est un fragment indépendant. Un tableau de bord de huit tuiles affiche les six rapides immédiatement et les deux lentes ensuite, plutôt que d'attendre la plus lente.
- **Graphiques légers** : rendu vectoriel, séries agrégées côté serveur à la résolution utile. Il est inutile d'envoyer 900 points pour un graphique large de 400 pixels.
- **Exports asynchrones** systématiques au-delà d'un seuil de volume, avec notification et téléchargement différé (BI-8).
- **Impression et hors ligne** : le pack de revue est un document autonome, consultable sans connexion — exigence réelle pour une réunion qui se tient parfois sans réseau.

**Le piège classique d'un module décisionnel est le tableau de bord que personne ne regarde.** La cause est presque toujours la même : trop de tuiles, aucune hiérarchie, et aucun lien avec une décision à prendre. La contre-mesure est de conception, pas technique — un tableau de bord par rôle, six tuiles au maximum par défaut, et chaque tuile doit répondre à une question que l'utilisateur se pose réellement. La mesure d'adoption de la section 17 sert précisément à détecter l'échec de cette conception.

## 8. Gouvernance des données

Le dictionnaire d'indicateurs comme actif gouverné

### 8.1 Le dictionnaire d'indicateurs

C'est l'apport de gouvernance le plus important de toute la Phase 2, et le plus facilement négligé. Sans lui, chaque rapport redéfinit ses propres calculs, les valeurs divergent, et le module perd sa crédibilité en quelques semaines.

****Structure du dictionnaire****

bi_metric — un indicateur = une définition, dans tout le produit

code identifiant stable, ex. 'ca_net'

libelle libellé affiché

definition définition en langage naturel, affichée au survol

formule expression sur les mesures de l'entrepôt

unite MGA | % | jours | quantité

proprietaire rôle ou personne responsable de la définition

axes_autorises dimensions d'analyse permises

roles_autorises qui peut consulter cet indicateur

maille_minimale interdit par ex. la maille individuelle

version, date_effet

• Une modification de définition CRÉE UNE VERSION ; l'ancienne est conservée.

• Les rapports impactés sont listés avant validation du changement.

• Les packs de revue déjà figés conservent la définition en vigueur à leur date.

• Rapports, tableaux de bord, prévisions, budgets et outils du copilote

consomment TOUS ce dictionnaire. Aucun calcul parallèle n'est autorisé.

### 8.2 Classification des données ajoutées

| Classe | Données Phase 2 | Règles associées |
|---|---|---|
| **Sensible** | Budget et objectifs non publiés, marges par client, prévisions non diffusées, cartographie des risques d'entreprise. | Accès restreint aux rôles de direction et de contrôle ; toute diffusion journalisée ; jamais transmise par le canal de messagerie sans décision explicite. |
| **Personnelle** | Numéro de téléphone, nom, historique de conversation, consentement et sa date. | Base légale explicite (consentement pour la prospection, exécution du contrat pour un avis de facture) ; minimisation ; droit d'accès et de retrait ; registre des traitements. |
| **Analytique dérivée** | Faits et agrégats de l'entrepôt, résultats de prévision. | Reconstructibles depuis l'opérationnel : sauvegarde allégée, mais rejeu documenté et testé. Les droits s'y appliquent à l'identique. |
| **Gouvernée** | Dictionnaire d'indicateurs, calendrier des jours ouvrés, modèles de message approuvés. | Versionnée, jamais supprimée ; toute modification auditée ; propriétaire identifié. |
| **Figée** | Packs de revue, budgets verrouillés, prévisions publiées. | Immuables par construction. Une correction crée une nouvelle version, jamais une modification en place. |

### 8.3 Rétention

| Donnée | Conservation active | Suppression |
|---|---|---|
| **Faits et agrégats analytiques** | Exercice courant + 3 ans en ligne | Archivage par partition ; reconstructibles depuis l'opérationnel |
| **Prévisions publiées et leur erreur mesurée** | 5 ans | Jamais purgées avant ce terme : sans historique d'erreur, la fiabilité d'un modèle n'est pas démontrable |
| **Budgets et packs de revue** | Durée de vie de l'entreprise | Jamais supprimés : ce sont des pièces de gouvernance |
| **Conversations du canal de messagerie** | 24 mois | Purge automatique ensuite ; suppression immédiate sur demande du destinataire, hors pièces rattachées à un document comptable |
| **Consentements et leurs révocations** | Durée de la relation + 3 ans | Conservés au-delà de la conversation : c'est la preuve du respect de la règle |
| **Journal d'envoi et de coût** | 24 mois en ligne | Export mensuel chiffré avant purge |

### 8.4 Qualité et réconciliation

- **Réconciliation obligatoire** : un contrôle automatique compare, à chaque rafraîchissement, les totaux de l'entrepôt à ceux de l'opérationnel sur un jeu d'indicateurs témoins. Tout écart bloque la publication du rafraîchissement et alerte, plutôt que de laisser un tableau de bord afficher un chiffre faux.
- **Complétude affichée** : lorsqu'une dimension comporte des valeurs non renseignées (client sans famille, article sans collection), le rapport affiche la part concernée plutôt que de la répartir silencieusement.
- **Une seule source de vérité par indicateur** : si un rapport a besoin d'un calcul absent du dictionnaire, on ajoute l'indicateur au dictionnaire — on ne le calcule pas dans le rapport.

## 9. Interopérabilité et outils tiers

Une seule intégration nouvelle, mais structurante

La Phase 2 n'ajoute qu'un tiers : la plateforme de messagerie professionnelle. C'est la première dépendance du produit qui combine coût variable, dépendance administrative et règles fonctionnelles imposées par le fournisseur. Elle mérite donc un traitement plus prudent que les précédentes.

| Intégration | Usage | Comportement en cas de panne du tiers |
|---|---|---|
| **Plateforme de messagerie professionnelle** | Envoi de documents, relances, confirmations ; réception bornée à un menu d'intentions. | Les envois sont mis en file avec un état visible ; l'e-mail reste disponible en repli manuel ; l'ERP fonctionne intégralement (WA-7). |
| **Serveur d'envoi d'e-mail (existant)** | Canal par défaut, diffusion planifiée des rapports. | Inchangé depuis la Phase 1 : file et réessai, état réel affiché. |
| **Ollama et repli cloud (existant)** | Outils analytiques du copilote sur la couche sémantique. | Le copilote s'annonce indisponible ; toute la restitution reste accessible sans lui. |
| **Stockage objet de sauvegarde (existant)** | Archives, exports volumineux, packs de revue. | Alerte immédiate ; conservation locale temporaire. |

### 9.1 Règles imposées par le fournisseur

Trois contraintes du fournisseur ont un effet direct sur la conception fonctionnelle et ne peuvent pas être contournées. Elles doivent être comprises avant de spécifier les écrans, sous peine de promettre des usages irréalisables.

| Règle | Conséquence sur la conception |
|---|---|
| **Modèles de message pré-approuvés pour toute conversation initiée par l'entreprise** | Il n'est pas possible d'envoyer un texte libre à un client qui n'a pas écrit récemment. Le produit doit donc gérer une bibliothèque de modèles avec leur statut d'approbation, leurs variables et leurs langues — et un envoi échouera si le modèle n'est pas approuvé. Cela impose aussi un délai : créer un nouveau type de relance n'est pas immédiat. |
| **Fenêtre de service après un message du destinataire** | Pendant cette fenêtre, la réponse est libre ; en dehors, seul un modèle approuvé passe. L'interface doit afficher le temps restant de la fenêtre, sinon l'utilisateur rédige une réponse qui sera refusée. |
| **Facturation à l'usage, selon des catégories de message** | Le coût dépend de la nature du message. Le produit doit imputer un coût à chaque envoi, l'agréger par tenant, et permettre un plafonnement. Aucune règle tarifaire n'est écrite dans le code : les catégories et leurs coûts sont paramétrés, selon la même discipline que les paramètres fiscaux. |

**Ces règles évoluent, et le document peut être périmé sur ce point [HYPOTHÈSE H8].** Les conditions des plateformes de messagerie professionnelle — catégories de conversation, mode de facturation, durée de la fenêtre de service, processus d'approbation — ont changé plusieurs fois ces dernières années. Le sprint 18 commence donc par une vérification directe de la documentation en vigueur, et non par du code. La conception retenue — modèles paramétrés, catégories et coûts en base, adaptateur isolé — est précisément faite pour absorber ces changements sans reprise.

### 9.2 Choix du mode de raccordement

| Option | Avantages | Inconvénients | Décision |
|---|---|---|---|
| **Raccordement direct à l'API du fournisseur** | Coût le plus bas, pas d'intermédiaire, maîtrise complète du comportement. | Démarches administratives à la charge de l'éditeur ou du client ; gestion des modèles et de leur approbation à implémenter. | **Retenu** |
| **Intermédiaire spécialisé** | Vérification administrative facilitée, gestion des modèles souvent fournie, mise en service plus rapide. | Surcoût par message, dépendance supplémentaire, moins de maîtrise sur les délais. | Repli si H9 n'est pas levée |
| **Passerelle non officielle** | Aucune démarche. | Violation des conditions d'utilisation, risque de suspension du numéro du client, aucune garantie de délivrabilité. | Écarté sans discussion |

## 10. Scalabilité

Une nouvelle dimension : le coût variable

| Dimension | Situation Phase 2 | Seuil où elle devient un problème | Option prévue |
|---|---|---|---|
| **Volume analytique** | Trois exercices de faits à la ligne de document, par tenant. Le POS est le plus gros contributeur en nombre de lignes. | Fenêtre de rafraîchissement dépassant la nuit, ou tableau de bord au-delà de 3 secondes malgré les agrégats. | Partitionnement par exercice dès la Phase 2 ; agrégats supplémentaires ; archivage des exercices anciens ; en dernier recours, moteur analytique dédié (écarté pour l'instant, voir section 11). |
| **Fenêtre de rafraîchissement** | Nouvelle contrainte d'exploitation, absente en Phase 1. | Chevauchement de deux exécutions, ou rafraîchissement non terminé à l'ouverture des bureaux. | Rafraîchissement incrémental et non complet ; verrou d'exécution ; deux files de worker distinctes pour que les tâches longues ne bloquent pas les courtes. |
| **Charge de calcul prévisionnel** | Quelques centaines de séries par tenant, recalculées périodiquement. | Durée de recalcul incompatible avec la fenêtre nocturne, ou concurrence avec le modèle de langage local pour le processeur. | Exécution planifiée hors des heures ouvrées et hors créneau du modèle local ; recalcul par lots ; séries à faible volume regroupées à une maille supérieure. |
| **Coût variable** | Dimension nouvelle. Chaque message sortant a un prix, imputé au tenant. | Dès le premier envoi en boucle non maîtrisé, ou dès qu'un client dépasse le volume prévu à son contrat. | Plafond mensuel par tenant appliqué techniquement, arrêt automatique des envois non critiques, limite de fréquence par destinataire, tableau de bord de coût. |
| **Équipe de développement** | Toujours une personne, qui assure désormais aussi le support de la Phase 1 en production. Dimension la plus contraignante. | Déjà atteinte : la capacité hebdomadaire baisse de 5 à 4,5 jours effectifs. | Réutilisation maximale du socle (neuf composants nouveaux seulement) ; rationalisation du catalogue de rapports plutôt que portage intégral ; budgets d'architecture vérifiés en CI. |
| **Nombre de tenants** | Entrepôt et agrégats portés par tenant dans la même base. | Le rafraîchissement devient linéaire au nombre de tenants : dix tenants font dix fois le travail nocturne. | Rafraîchissement séquencé par tenant avec priorité ; décalage des fenêtres ; isolation d'un tenant volumineux sur sa propre instance sans changement de code. |

### 10.1 Budgets d'architecture révisés

| Budget | Fin Phase 1 | Révisé Phase 2 | Justification |
|---|---|---|---|
| **Modèles** | 245 | 285 | ~14 pour l'entrepôt (dimensions et faits), ~6 pour la couche sémantique et la gouvernance, ~8 pour Forecast (série, modèle, ajustement, erreur), ~8 pour Strategy (objectif, résultat clé, budget, version, ligne, écart, initiative, risque), ~6 pour le canal (modèle de message, consentement, conversation, envoi, coût). |
| **Endpoints** | 760 | 840 | Endpoints de requête guidée, fragments de tuiles, points de terminaison entrant et sortant du canal, outils analytiques du copilote. |
| **Écrans (total)** | 148 | 180 | Tableaux de bord, constructeur, catalogue rationalisé, écrans de prévision, budget et revue, configuration et conversation du canal. |
| **Écrans legacy** | 0 | 0 — maintenu | La Phase 1 a supprimé le legacy de son périmètre. Le budget reste à zéro : aucun écran de la Phase 2 ne crée de dette d'interface. |
| **Rapports** | — | à fixer au sprint 1 | Nouveau budget. Le catalogue hérité est audité puis rationalisé (H6) ; le nombre retenu devient un plafond vérifié en CI, pour éviter que le catalogue ne recommence à gonfler par accumulation. |

**Le budget de rapports est la mesure la plus utile de cette section.** Un catalogue de rapports est la partie d'un ERP qui dérive le plus facilement : chaque demande client produit un rapport de plus, personne n'en supprime jamais, et au bout de trois ans plus personne ne sait lequel est juste. Un plafond vérifié en intégration continue force à arbitrer — ajouter un rapport oblige à en retirer un, ou à le rendre paramétrable plutôt que de le dupliquer.

## 11. Choix technologiques

Trois décisions, toutes orientées par la contrainte solo

### 11.1 Entrepôt analytique

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Schéma en étoile dans le PostgreSQL existant** | Aucun composant à exploiter en plus ; transactions cohérentes avec l'opérationnel ; RLS et droits déjà en place ; sauvegarde unique ; vues matérialisées et partitionnement suffisants au volume visé. | Concurrence entre charge analytique et charge transactionnelle sur la même instance ; plafond de performance atteint plus tôt qu'avec un moteur en colonnes. | **Retenu** |
| **Moteur analytique embarqué en colonnes** | Performance d'agrégation très supérieure à volume égal, sans serveur supplémentaire. | Second modèle de données à synchroniser ; droits et RLS à reconstruire ; complexité de cohérence pour un gain que le volume actuel ne justifie pas. | Repli si H7 échoue |
| **Entrepôt infogéré** | Performance et élasticité sans exploitation. | Coût récurrent en devises, sortie des données hors du serveur du client, dépendance réseau pour la restitution — rédhibitoire dans le contexte cible. | Écarté |

### 11.2 Outil de restitution

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Construction sur le socle de la Phase 1** | Cohérence visuelle et ergonomique totale ; un seul modèle de droits ; légèreté sur réseau contraint ; le data grid, le tableau croisé et les filtres existent déjà. | Le constructeur de rapports est à écrire ; les fonctions les plus avancées d'un outil spécialisé ne seront pas atteintes. | **Retenu** |
| **Outil de BI open source intégré** | Constructeur, graphiques et diffusion immédiatement disponibles ; économie de plusieurs sprints. | Second modèle de droits à maintenir en cohérence avec les rôles WideHalo — c'est le point disqualifiant, car une divergence de droits est une fuite de données. S'y ajoutent une rupture d'ergonomie visible et un conteneur supplémentaire à exploiter. | Écarté, repli partiel possible pour l'exploration experte |
| **Tableur comme outil de restitution** | Aucun développement. | Chiffres non gouvernés, versions divergentes, aucune traçabilité : c'est exactement le problème que la Phase 2 doit résoudre. | Écarté |

### 11.3 Moteur de prévision

Le choix est guidé par la profondeur d'historique réellement disponible et par l'exigence d'interprétabilité. Avec deux à trois cycles annuels et des séries mensuelles, un modèle d'apprentissage automatique n'a rien à apprendre de plus qu'un lissage exponentiel bien paramétré — mais il devient impossible à expliquer à un dirigeant qui conteste le chiffre. L'explicabilité n'est pas un confort ici : c'est la condition de l'adoption.

| Option | Verdict |
|---|---|
| **Bibliothèque statistique Python établie : moyenne mobile, lissages exponentiels simple, double et triple, régression avec régresseurs, référence naïve saisonnière, sélection par rétrotest glissant.** | **Retenu.** Interprétable, léger, sans service supplémentaire, adapté à la profondeur d'historique. Le choix du modèle et son score sont consultables (FOR-3). |
| **Bibliothèque de prévision automatisée avec décomposition (tendance, saisonnalité, jours particuliers).** | Envisageable en complément, sur les seules séries à forte saisonnalité. À arbitrer au sprint 11 sur des données réelles, pas par principe. |
| **Apprentissage automatique (forêts, gradient, réseaux).** | Écarté en Phase 2. Aucun gain démontrable à ce volume, coût de calcul sur un serveur déjà partagé avec le modèle de langage local, et perte d'explicabilité rédhibitoire pour l'usage visé. |

### 11.4 Briques confirmées sans réexamen

Django 5.2 LTS, django-ninja, PostgreSQL, django-cotton avec HTMX et Alpine, Tailwind et DaisyUI, FastAPI pour le gateway IA, Ollama avec repli cloud, Hetzner avec Coolify, Docker Compose et Caddy : tout est confirmé sans réexamen. La Phase 2 est précisément conçue pour ne rien changer à la pile — c'est ce qui permet de livrer quatre modules en vingt-deux sprints avec une capacité en baisse.

## 12. Socle analytique et couche sémantique

Ce qui doit être juste avant que quoi que ce soit soit affiché

Les quatre modules de la Phase 2 partagent une même source. Si cette source est fausse ou incohérente, les quatre modules sont faux simultanément — et le défaut est invisible, puisque tout s'affiche normalement. C'est pourquoi les cinq premiers sprints ne produisent aucune fonctionnalité visible par le client : ils construisent la source.

### 12.1 Entrepôt en étoile

****Modèle dimensionnel — Phase 2****

DIMENSIONS CONFORMES (partagées par tous les faits)

dim_temps jour · semaine · mois · trimestre · exercice

jour ouvré · jour férié · saison ← paramétré, pas codé

dim_tiers client · fournisseur · famille · zone · commercial

dim_article article · variante · famille · collection · saison

dim_point_vente point de vente · caisse · canal

dim_compte compte PCG 2005 · classe · nature

dim_utilisateur auteur d'une opération ou d'un ajustement

FAITS (à la ligne de document — condition de l'exploration du détail)

fact_vente ligne de devis, commande, BL, facture, avoir

fact_ticket_pos ligne de ticket de caisse

fact_encaissement règlement et lettrage

fact_ecriture ligne d'écriture comptable

fact_prevision prévision publiée, par version

fact_budget ligne de budget, par version

• Chaque fait porte tenant_id ; les policies RLS s'appliquent à l'entrepôt.

• Faits partitionnés par exercice.

• Le modèle est conçu pour accueillir fact_stock, fact_of et fact_achat

en Phase 3 SANS reprise des dimensions.

### 12.2 Rafraîchissement

- **Incrémental par défaut** : seules les lignes créées ou modifiées depuis la dernière exécution sont retraitées. Un rechargement complet reste possible mais explicite, et journalisé comme une opération exceptionnelle.
- **Rejouable sans doublon** : rejouer une période déjà chargée doit produire le même résultat. C'est la condition pour corriger un incident sans repartir de zéro, et c'est testé explicitement.
- **Verrouillé** : deux exécutions ne peuvent pas se chevaucher. Sans verrou, un rafraîchissement qui dépasse sa fenêtre entre en collision avec le suivant et corrompt les agrégats.
- **Contrôlé avant publication** : un jeu d'indicateurs témoins est rapproché de l'opérationnel à chaque exécution. Un écart bloque la publication et alerte, plutôt que de laisser un chiffre faux s'afficher.
- **Visible** : dernière exécution, durée, volume traité et échec éventuel sont affichés à l'utilisateur sur chaque tableau de bord, pas réservés à un écran d'administration.

### 12.3 Couche sémantique et moteur de requête guidé

La structure du dictionnaire d'indicateurs est décrite en section 8.1. Le point d'architecture est ici : c'est le seul chemin d'accès aux données analytiques. Aucun écran, aucun rapport, aucun outil du copilote n'interroge l'entrepôt directement.

****Chemin d'accès unique aux données analytiques****

```
Utilisateur, rapport, tableau de bord, prévision, budget, copilote
   │  demande exprimée en MESURES et DIMENSIONS déclarées
   ▼
┌─ MOTEUR DE REQUÊTE GUIDÉ ─────────────────────────────────────┐
│  ✓ la mesure existe-t-elle au dictionnaire ?                  │
│  ✓ l'axe demandé est-il autorisé pour cette mesure ?          │
│  ✓ le rôle autorise-t-il cette mesure à cette maille ?        │
│  ✓ le périmètre du rôle est-il appliqué AVANT agrégation ?    │
└───────────────────────────────────────────────────────────────┘
   │  SQL construit par le moteur, paramétré, jamais concaténé
   ▼
Entrepôt (RLS active, rôle applicatif non superutilisateur)
⚠  AUCUN champ de saisie de requête n'est exposé à l'utilisateur.
   AUCUN outil tiers n'accède à l'entrepôt.
   Le copilote parle ce vocabulaire et ne peut pas en sortir.
```

**C'est la réponse à une question légitime : comment faire du self-service sans SQL libre ?** En donnant à l'utilisateur un vocabulaire riche plutôt qu'un langage ouvert. Il compose librement dans ce vocabulaire — croiser n'importe quelle mesure avec n'importe quel axe autorisé, filtrer, trier, sauvegarder, partager — mais il ne peut pas écrire une requête. Le gain est triple : les droits restent appliqués, les définitions restent uniques, et le copilote hérite gratuitement d'un moyen sûr d'interroger les données. La contrepartie est réelle : un besoin d'analyse très inhabituel exigera d'ajouter une mesure au dictionnaire plutôt que de bricoler une requête. C'est un coût accepté.

## 13. Spécifications fonctionnelles — Phase 2

Business Intelligence • Forecast • Strategy • WhatsApp

L'ordre de présentation suit l'ordre de dépendance : la BI produit les chiffres, Forecast les projette, Strategy les confronte à une intention, WhatsApp les diffuse. Trente-huit critères d'acceptation, formulés pour être traduits en tests.

### 13.1 Module Business Intelligence

**Objectif** : qu'un utilisateur métier obtienne une réponse chiffrée juste, datée et explicable, sans passer par l'éditeur. Le succès de ce module ne se mesure pas au nombre de rapports livrés mais au nombre de demandes de rapport qui cessent d'arriver au support.

| Écran | Contenu et interactions |
|---|---|
| **Tableau de bord par rôle** | Grille de tuiles composée par l'administrateur pour chaque rôle, personnalisable par l'utilisateur. Six tuiles par défaut, chargement indépendant, état de fraîcheur affiché. Chaque tuile mène au rapport qui la détaille. |
| **Catalogue de rapports** | Rapports rationalisés et industrialisés sur la couche sémantique, classés par domaine, avec description, propriétaire et indicateurs utilisés. Recherche et favoris. |
| **Constructeur self-service** | Sélection de mesures et de dimensions déclarées, filtres, regroupements, tri, bascule liste / tableau croisé / graphique, aperçu progressif. Enregistrement comme rapport personnel ou partagé. Aucun champ de requête libre. |
| **Exploration du détail** | Depuis toute valeur agrégée, accès aux lignes qui la composent puis aux pièces d'origine — sans export intermédiaire, dans les limites des droits du rôle. |
| **Diffusion planifiée** | Envoi périodique d'un rapport ou d'un tableau de bord à une liste de destinataires, par e-mail puis par le canal de messagerie. Journalisée avec périmètre et statut. |
| **Gouvernance du dictionnaire** | Consultation et gestion des indicateurs : définition, formule, propriétaire, axes, rôles, version. Liste des rapports impactés avant tout changement. Écran destiné au contrôleur de gestion, pas à l'éditeur. |
| **Journal de rafraîchissement** | Historique des exécutions, durées, volumes, échecs et résultats des contrôles de réconciliation. Déclenchement manuel si le rôle l'autorise. |

**Règles de gestion**

- Tout chiffre affiché provient d'un indicateur du dictionnaire. Aucun calcul n'est écrit dans un rapport ou dans un gabarit.
- Les droits sont appliqués avant agrégation, jamais après (voir section 6.1).
- Un rapport partagé reste sous la responsabilité de son créateur, mais son périmètre de données s'adapte au rôle de celui qui l'ouvre : deux utilisateurs peuvent légitimement voir des valeurs différentes dans le même rapport, et l'interface l'indique.
- Un rafraîchissement dont le contrôle de réconciliation échoue n'est pas publié.
- Aucun rapport n'est créé sans propriétaire identifié — c'est la condition pour pouvoir le supprimer un jour.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **BI-1** | Chaque indicateur porte une définition, une formule, un propriétaire et une version ; un test de cohérence vérifie que deux écrans affichant le même indicateur sur le même périmètre renvoient la même valeur. |
| **BI-2** | Le constructeur n'accepte que des mesures et dimensions déclarées ; un test de CI vérifie qu'aucun endpoint n'accepte de SQL ni de fragment de requête en entrée. |
| **BI-3** | Les rapports retenus à l'issue de la rationalisation sont reconstruits sur la couche sémantique et rapprochés à l'ariary près de leur version d'origine. |
| **BI-4** | L'état du rafraîchissement (dernière exécution, durée, volume, échec) est visible sur chaque tableau de bord, sans passer par un écran d'administration. |
| **BI-5** | Un tableau de bord de six tuiles se charge en moins de 3 s sur profil réseau dégradé, sur trois exercices d'historique ; une tuile lente dégrade seule. |
| **BI-6** | Un utilisateur ne voit dans un rapport que les données que son rôle l'autorise à consulter, y compris en agrégé (test par rôle et par maille). |
| **BI-7** | Une diffusion planifiée est journalisée avec son destinataire, son périmètre, son canal et son statut. |
| **BI-8** | Un export dépassant le seuil de volume est traité en asynchrone avec téléchargement différé ; l'interface n'est jamais bloquée. |
| **BI-9** | Toute modification de définition d'un indicateur crée une version, conserve la précédente, liste les rapports impactés et apparaît au journal d'audit. |
| **BI-10** | Depuis toute valeur agrégée, l'utilisateur atteint en un clic les lignes qui la composent, dans la limite de ses droits ; le blocage éventuel est expliqué. |

### 13.2 Module Forecast

**Objectif** : produire une prévision de ventes, d'encaissements et de trésorerie dont l'erreur est connue et publiée. Un module de prévision se juge à une seule chose : est-il utilisé six mois après sa livraison. Il ne l'est que si les utilisateurs peuvent le corriger et vérifier qu'il se trompe moins qu'eux.

**Prévision et simulation ne répondent pas à la même question, et la confusion est fréquente.** La simulation livrée en Phase 1 répond à « que se passe-t-il si je décide X » : elle est déterministe, instantanée, et ne prétend rien prédire. La prévision répond à « que va-t-il probablement se passer si rien ne change » : elle est statistique, périodique, et assortie d'une mesure d'erreur. Les deux se rejoignent en un point précis : la prévision publiée devient le scénario de référence à partir duquel la simulation calcule des écarts (FOR-10). C'est cette articulation qui rend l'ensemble cohérent plutôt que redondant.

| Écran | Contenu et interactions |
|---|---|
| **Atelier de prévision** | Par série (famille, article, client, canal) : courbe historique, prévision statistique, ajustement humain, erreur mesurée, comparaison à la référence naïve. Saisie directe par période avec motif obligatoire. |
| **Diagnostic de série** | Profondeur d'historique, saisonnalité détectée, valeurs manquantes, points marqués comme exceptionnels, modèle retenu et son score. Écran qui évite le débat stérile sur « pourquoi ce chiffre ». |
| **Prévision consolidée** | Agrégation des séries à la maille de pilotage, avec la part statistique et la part ajustée distinguées. |
| **Prévision d'encaissement** | Dérivée de l'encours réel et du comportement de règlement observé par client, et non d'un délai théorique unique appliqué à tous. |
| **Trésorerie à douze mois** | Encaissements prévus, décaissements connus et récurrents, échéanciers, avec les hypothèses affichées. Prolonge à douze mois la projection à treize semaines de la Phase 1. |
| **Suivi de la qualité de prévision** | Erreur par série et par période échue, biais, et apport mesuré de l'ajustement humain — par contributeur. Écran délicat, dont l'objet est d'améliorer la prévision, pas de désigner un responsable ; sa restitution est donc agrégée par défaut. |
| **Calendrier** | Jours ouvrés, jours fériés malgaches, périodes de saison, paramétrés dans la table de référence versionnée. |

**Méthode retenue**

- **Préparation** : agrégation à la période utile, traitement des valeurs manquantes, exclusion de l'apprentissage des points marqués comme exceptionnels (rupture d'approvisionnement, opération promotionnelle isolée) sans les supprimer de l'historique.
- **Modèles** : référence naïve saisonnière, moyenne mobile, lissages exponentiels simple, double et triple, régression avec régresseurs de calendrier.
- **Sélection** : rétrotest glissant sur les périodes échues, et non ajustement sur l'historique complet — c'est la distinction qui sépare une erreur honnête d'une erreur flatteuse.
- **Erreur publiée** : erreur absolue moyenne en pourcentage, erreur pondérée par le volume, et biais. Le biais est le plus utile des trois en gestion : une prévision systématiquement basse se corrige, une prévision aléatoire ne se corrige pas.
- **Repli explicite** : si l'historique est insuffisant pour détecter une saisonnalité fiable, la série est prévue sans composante saisonnière et l'écran le dit, plutôt que d'inventer un cycle sur un an et demi de données.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **FOR-1** | La référence naïve saisonnière est toujours calculée et affichée ; un modèle qui ne la bat pas sur le rétrotest est signalé comme tel à l'utilisateur. |
| **FOR-2** | L'erreur (absolue moyenne, pondérée et biais) est affichée pour chaque série, mesurée par rétrotest glissant et non par ajustement sur l'historique complet. |
| **FOR-3** | La sélection automatique du modèle est reproductible et son motif est consultable (modèle retenu, score, fenêtre de test, modèles écartés). |
| **FOR-4** | Les points marqués comme exceptionnels sont exclus de l'apprentissage sans disparaître de l'historique affiché. |
| **FOR-5** | Le calendrier applique les jours ouvrés et fériés malgaches lus dans la table de référence ; un test vérifie qu'aucune date fériée n'est écrite dans le code. |
| **FOR-6** | Tout ajustement humain est tracé (auteur, date, valeur avant et après, motif) et réversible ; la prévision statistique reste consultable en parallèle. |
| **FOR-7** | L'apport de l'ajustement humain est mesuré : l'erreur de la prévision ajustée est comparée à celle de la prévision statistique sur les périodes échues. |
| **FOR-8** | La prévision de ventes intègre les ventes POS au même titre que les ventes facturées, sans double comptage des tickets ensuite facturés. |
| **FOR-9** | La prévision d'encaissement dérive du comportement de règlement observé par client, et non d'un délai théorique unique. |
| **FOR-10** | La prévision publiée est disponible comme scénario de référence dans la simulation financière de la Phase 1, avec sa version et sa date. |

### 13.3 Module Strategy

**Objectif** : que la revue de direction se prépare dans WideHalo plutôt que dans un tableur repris à la main chaque mois, et qu'un écart budgétaire soit expliqué là où il est constaté. Le risque de ce module n'est pas technique : c'est de produire un exercice bureaucratique que personne n'utilise.

| Écran | Contenu et interactions |
|---|---|
| **Objectifs et résultats clés** | Cascade entreprise → équipe → individu. Chaque résultat clé est adossé à un indicateur du dictionnaire avec sa cible et son échéance ; l'avancement se calcule, il ne se déclare pas. |
| **Initiatives et plans d'action** | Actions rattachées à un objectif : responsable, échéance, état, avancement, chatter. Réutilise le moteur de workflow et le chatter de la Phase 1. |
| **Construction du budget** | Saisie par axe (famille, point de vente, compte) et par période ; initialisation possible depuis un scénario de simulation ou depuis une prévision publiée ; versions successives ; verrouillage. |
| **Suivi budgétaire** | Tableau réel / budget / prévision avec écart en valeur et en pourcentage, seuil d'alerte paramétrable, et commentaire de gestion rattaché à la ligne — pas dans un document séparé qui se perd. |
| **Pack de revue de performance** | Génération d'un document de revue à date, figé et horodaté, avec les valeurs et les définitions en vigueur à sa génération. Diffusable et consultable hors connexion. |
| **Cartographie des risques** | Risques d'entreprise avec probabilité, impact, mesure de maîtrise, propriétaire et date de dernière réévaluation. Toute réévaluation est auditée. |
| **Tableau de bord de direction** | Composition dédiée au rôle dirigeant : avancement des objectifs, écarts significatifs, trésorerie projetée, alertes. Six tuiles au maximum. |

**Règles de gestion**

- Un objectif sans indicateur mesurable ne peut pas être créé. C'est une contrainte délibérément rigide : elle élimine les objectifs déclaratifs qui ne se suivent pas.
- Un budget verrouillé est immuable ; une révision crée une version horodatée et l'ancienne reste consultable et comparable.
- L'écart se calcule toujours sur la même définition d'indicateur que le réel. Un budget construit sur une définition et un réel mesuré sur une autre produit un écart dépourvu de sens — c'est l'erreur classique de ce type de module.
- Un écart dépassant le seuil paramétré exige un commentaire de gestion avant que la revue puisse être clôturée. Le seuil évite que l'obligation ne devienne une formalité sur toutes les lignes.
- Le pack de revue est figé : les valeurs, les définitions et les commentaires y sont conservés en l'état. Un tableau de bord qui change après la réunion rend la réunion inutile.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **STR-1** | La création d'un objectif sans indicateur du dictionnaire est refusée ; l'avancement est calculé depuis l'indicateur, jamais saisi à la main. |
| **STR-2** | La cascade affiche la contribution de chaque niveau au niveau supérieur et consolide l'avancement sans double comptage. |
| **STR-3** | Un budget verrouillé refuse toute modification, y compris par appel direct de l'API ; une révision crée une version horodatée et l'ancienne reste consultable. |
| **STR-4** | Un budget peut être initialisé depuis un scénario de simulation ou une prévision publiée, avec conservation de la référence et de la version de la source. |
| **STR-5** | L'écart budget / réel est calculé sur la même définition d'indicateur que le réel ; un test vérifie l'identité des définitions employées de part et d'autre. |
| **STR-6** | Un écart dépassant le seuil paramétré empêche la clôture de la revue tant qu'aucun commentaire de gestion n'est saisi sur la ligne concernée. |
| **STR-7** | Un pack de revue réouvert un mois plus tard affiche exactement les mêmes valeurs, les mêmes définitions et les mêmes commentaires qu'à sa génération. |
| **STR-8** | La cartographie des risques restitue probabilité, impact, mesure de maîtrise, propriétaire et date de réévaluation ; toute réévaluation apparaît au journal d'audit. |

### 13.4 Module WhatsApp

**Objectif** : atteindre le destinataire sur le canal qu'il utilise réellement. À Madagascar, un devis envoyé par courrier électronique à une PME cliente a une probabilité de lecture sensiblement plus faible que le même document annoncé par messagerie instantanée. Ce module ne crée pas de fonctionnalité nouvelle : il rend efficaces celles qui existent.

****Chaîne d'envoi — le canal est un adaptateur, pas un module autonome****

```
Événement métier (devis validé, échéance dépassée, commande confirmée…)
   │
   ▼
MOTEUR DE NOTIFICATION — livré en Phase 1, inchangé
   destinataire · gabarit · canal · statut · réessai
   ├─> canal interne (Phase 1)
   ├─> canal e-mail (Phase 1) — reste le défaut
   └─> canal messagerie (Phase 2) — ADAPTATEUR
        │
┌───────▼──────────────────────────────────────────────────────┐
│ CONTRÔLES AVANT ENVOI — côté code, à chaque message           │
│   ✓ consentement enregistré et non révoqué ?                  │
│   ✓ hors fenêtre de service → modèle approuvé obligatoire ?   │
│   ✓ plafond de coût du tenant non atteint ?                   │
│   ✓ fréquence par destinataire respectée ?                    │
└───────────────────────────────────────────────────────────────┘
        │ si et seulement si les quatre contrôles passent
        ▼
Plateforme du fournisseur → destinataire
        │
        ▼ statut de livraison, réponse entrante
Chatter de l'objet concerné + journal d'envoi et de coût
```

| Écran | Contenu et interactions |
|---|---|
| **Configuration du canal** | Compte, numéro, jetons, activation par tenant. Affiche explicitement quelles données personnelles sortent du serveur et vers qui. Désactivé par défaut. |
| **Bibliothèque de modèles** | Modèles de message avec leur statut d'approbation, leurs variables, leurs langues (français, malgache), leur catégorie et le coût associé. Un modèle non approuvé est inutilisable et l'écran le dit. |
| **Consentement par tiers** | État, date, origine et historique du consentement ; révocation ; préférence de canal. Consultable depuis la fiche du tiers. |
| **Conversation** | Fil entrant et sortant avec statut de livraison, modèle employé, temps restant de la fenêtre de service et coût imputé. Intégré au chatter de l'objet concerné. |
| **Parcours entrant** | Menu d'intentions déclarées : statut d'une commande, solde, prochaine échéance, demande de rappel, escalade vers un humain. Aucune génération libre de réponse. |
| **Journal d'envoi et de coût** | Tous les envois avec modèle, destinataire, statut, catégorie et coût ; consommation mensuelle par tenant face au plafond ; alertes. |

**Usages couverts**

| Sortant | Entrant (borné) |
|---|---|
| Devis validé, facture émise, relance d'échéance, confirmation de commande, avis d'expédition, ticket de caisse dématérialisé (lien avec le POS), diffusion d'un pack de revue à un dirigeant. | Statut d'une commande, solde et prochaine échéance, demande de rappel, révocation du consentement, escalade vers un humain. |

**Le canal reste un confort, jamais un chemin critique — comme le copilote.** Aucun processus métier ne dépend de la disponibilité du canal : un devis se valide, une facture s'émet et une relance s'enregistre même canal coupé. Les envois sont mis en file avec un état visible, et l'e-mail reste le canal par défaut. Cette règle a une conséquence commerciale à assumer : le canal ne doit pas être vendu comme une garantie de délivrabilité, puisqu'il dépend d'un tiers, d'un numéro vérifié et de modèles approuvés par ce tiers.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **WA-1** | Aucun message n'est envoyé sans consentement enregistré et non révoqué ; le contrôle a lieu à l'envoi, et un test vérifie qu'aucune voie applicative (import, action de masse, tâche planifiée) ne le contourne. |
| **WA-2** | La révocation du consentement est effective immédiatement, déclenchable par un seul message du destinataire, et journalisée. |
| **WA-3** | Hors fenêtre de service, seul un modèle approuvé est envoyé ; toute tentative d'envoi libre est refusée côté serveur avec un message explicite. |
| **WA-4** | Chaque envoi est journalisé avec son modèle, ses variables, son destinataire, son statut de livraison, sa catégorie et son coût imputé. |
| **WA-5** | Un plafond mensuel par tenant arrête les envois non critiques et alerte l'administrateur avant d'être atteint ; une limite de fréquence par destinataire empêche l'envoi en boucle. |
| **WA-6** | Les messages entrants et sortants apparaissent dans le chatter de l'objet concerné (tiers, devis, facture) sans action manuelle. |
| **WA-7** | Canal indisponible, l'ERP reste intégralement fonctionnel ; les envois sont mis en file avec un état visible et repris automatiquement. |
| **WA-8** | Le parcours entrant est borné à un menu d'intentions déclarées ; aucune génération libre de réponse n'est possible, et un test le vérifie. |
| **WA-9** | Tout chiffre communiqué par le canal provient d'un outil en lecture seule du gateway, avec les mêmes restrictions de rôle et de tenant que l'interface. |
| **WA-10** | L'écran de configuration énonce quelles données personnelles sortent du serveur et vers qui ; l'activation du canal est journalisée ; aucune règle tarifaire n'est écrite dans le code. |

## 14. Plan de développement — sprints hebdomadaires

22 semaines, 6 blocs, une source juste avant tout affichage

Même cadence hebdomadaire qu'en Phase 1, avec une différence importante : la capacité disponible baisse. Le développeur assure désormais aussi le support d'un produit en production, et l'estimation retient 4,5 jours effectifs par semaine au lieu de 5. Ignorer cette baisse serait la première cause de dérapage du plan.

### 14.1 Ordonnancement et dépendances

****Chaîne de dépendances des blocs****

```
  S1        S2→S5              S6→S9        S10→S13       S14→S17       S18→S21     S22
┌──────┬────────────────────┬────────────┬─────────────┬─────────────┬────────────┬─────┐
│ CAD  │ A SOCLE ANALYTIQUE │ B    BI    │ C  FORECAST │ D  STRATEGY │ E WHATSAPP │  F  │
└──────┴────────────────────┴────────────┴─────────────┴─────────────┴────────────┴─────┘
L'ordre suit l'ordre de dépendance, pas l'ordre de valeur perçue.
Le socle analytique et la couche sémantique conditionnent les quatre
modules : aucun chiffre n'est affiché avant que la source soit juste.
```

****Dépendances croisées à surveiller****

```
A (couche sémantique) ───> B, C, D
   BI, Forecast et Strategy consomment le MÊME dictionnaire d'indicateurs.
   Une définition ajoutée tard oblige à reprendre les rapports, les
   prévisions et les écarts déjà construits.
B (BI) ───> C (Forecast) ───> D (Strategy)
   les séries de prévision viennent de l'entrepôt ; le budget s'initialise
   depuis une prévision publiée. Chaque bloc a besoin du précédent, d'où
   l'absence de parallélisation possible.
E (WhatsApp) ───> indépendant des trois autres
   seul bloc déplaçable dans le calendrier. Il est placé en fin parce que sa
   dépendance administrative (H9) est la moins maîtrisée : un blocage y
   coûte moins cher en fin de plan.
PHASE 3 ───> extension de C (Forecast)
   la prévision de besoins matière et de charge d'atelier attend les modules
   Stock, Achats et Production. Le modèle dimensionnel les accueillera
   sans reprise.
```

**Cinq sprints sans rien de visible : c'est le pari de la Phase 2.** Le bloc A ne produit aucun écran que le client puisse apprécier. La tentation sera forte de livrer un premier tableau de bord au sprint 2 pour rassurer. C'est précisément ce qu'il faut éviter : un tableau de bord construit avant la couche sémantique redéfinit ses propres calculs, et il devient la première source de divergence qu'il faudra corriger ensuite. La contre-mesure est de communiquer autrement sur ces cinq semaines — en montrant le journal de rafraîchissement et le dictionnaire, qui sont démontrables dès le sprint 3.

### 14.2 Bloc A — Cadrage et socle analytique (S1 à S5)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S1** | Cadrage et rationalisation du catalogue | Audit du catalogue de rapports hérité : usage réel, redondances, incohérences de calcul — lève H6 et produit un arbitrage écrit (conserver / fusionner / rendre paramétrable / supprimer) ainsi que le budget de rapports vérifié en CI. Ligne de base des parcours UC9 à UC14 sur la pratique actuelle. Diagnostic de profondeur d'historique par famille. | 6 | 2,5 |
| **S2** | Entrepôt en étoile | Dimensions conformes (temps, tiers, article, point de vente, compte, utilisateur) et faits à la ligne de document ; partitionnement par exercice ; policies RLS étendues à l'entrepôt ; index. Banc d'essai de volume — lève H7 sur un jeu simulé à trois exercices. | 7 | 3 |
| **S3** | Rafraîchissement et dictionnaire | Chargement incrémental rejouable sans doublon, verrou d'exécution, deux files de worker distinctes, contrôle de réconciliation bloquant avant publication, journal visible (c-refresh-badge). Structure et écran du dictionnaire d'indicateurs, avec c-metric-value. | 6 | 2,5 |
| **S4** | Moteur de requête guidé | Traduction d'une demande en mesures et dimensions déclarées vers une requête paramétrée ; application du périmètre du rôle avant agrégation ; contrôle des axes et des mailles autorisés ; test de CI interdisant tout endpoint acceptant du SQL en entrée (BI-2). Agrégats matérialisés. | 7 | 3 |
| **S5** | Composants de restitution | c-dashboard-grid avec chargement et dégradation par tuile, c-chart léger avec valeurs accessibles en texte. Campagne de mesure de l'objectif de 3 secondes sur profil réseau dégradé (BI-5). | 7 | 3 |

> Fin du bloc A — jalon J1 : le dictionnaire et le journal de rafraîchissement sont démontrables, et un tableau de bord quelconque peut désormais être composé en quelques heures. Point de recalibrage des estimations (lève H11).

### 14.3 Bloc B — Business Intelligence (S6 à S9)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S6** | Catalogue industrialisé | Reconstruction des rapports retenus au sprint 1 sur la couche sémantique, avec rapprochement à l'ariary près de leur version d'origine (BI-3) ; catalogue avec domaine, description, propriétaire et indicateurs utilisés ; favoris. | 6 | 2,5 |
| **S7** | Constructeur self-service | c-report-builder : mesures, dimensions, filtres, regroupements, bascule liste / tableau croisé / graphique, aperçu progressif, enregistrement personnel ou partagé. Mesure UC9. | 7 | 3 |
| **S8** | Tableaux de bord et diffusion | Composition par rôle et personnalisation utilisateur ; exploration du détail depuis un agrégé jusqu'à la pièce, bornée par les droits (BI-10) ; diffusion planifiée par e-mail, journalisée (BI-7). Mesure UC10. | 6 | 2,5 |
| **S9** | Droits, exports, gouvernance | Tests de restitution rôle par rôle et maille par maille contre la fuite par agrégat (BI-6) ; exports asynchrones au-delà du seuil (BI-8) ; versionnement des définitions avec liste des rapports impactés (BI-9) ; test de cohérence inter-écrans (BI-1) ; outils analytiques du copilote sur la couche sémantique. | 5 | 2 |

> Fin du bloc B — jalon J2 : première valeur visible pour le client. C'est le jalon à utiliser en démonstration, pas le sprint 5.

### 14.4 Bloc C — Forecast (S10 à S13)

La difficulté de ce bloc est statistique et non logicielle. Deux sprints sur quatre portent sur la justesse de la méthode et sur la mesure honnête de l'erreur — c'est ce qui détermine si le module sera encore utilisé six mois après sa livraison.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S10** | Préparation des séries et calendrier | Agrégation à la période utile, traitement des valeurs manquantes, marquage et exclusion d'apprentissage des points exceptionnels sans les supprimer (FOR-4) ; calendrier des jours ouvrés et fériés malgaches en table versionnée (FOR-5) ; intégration des ventes POS sans double comptage (FOR-8). Diagnostic de saisonnalité sur données réelles — lève H10. | 6 | 2,5 |
| **S11** | Modèles et mesure de l'erreur | Référence naïve saisonnière toujours calculée (FOR-1), moyenne mobile, lissages exponentiels, régression avec régresseurs de calendrier ; sélection par rétrotest glissant, reproductible et justifiée (FOR-3) ; publication de l'erreur absolue, pondérée et du biais (FOR-2) ; repli sans composante saisonnière annoncé à l'écran. Arbitrage sur l'opportunité d'une bibliothèque de décomposition complémentaire. | 7 | 3 |
| **S12** | Prévision collaborative | c-forecast-editor : historique, statistique et ajustement sur une même courbe, saisie par période avec motif obligatoire, réversibilité (FOR-6) ; écran de diagnostic de série ; prévision consolidée distinguant part statistique et part ajustée. Mesure UC11. | 6 | 2,5 |
| **S13** | Encaissement, trésorerie, qualité | Prévision d'encaissement dérivée du comportement de règlement observé par client (FOR-9) ; trésorerie à douze mois avec hypothèses affichées ; suivi de la qualité de prévision et mesure de l'apport de l'ajustement humain (FOR-7) ; publication de la prévision comme scénario de référence de la simulation Phase 1 (FOR-10). | 6 | 2,5 |

> Fin du bloc C — jalon J3 : la prévision est publiée avec son erreur, et l'articulation avec la simulation de la Phase 1 est démontrable.

### 14.5 Bloc D — Strategy (S14 à S17)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S14** | Objectifs et initiatives | Objectifs et résultats clés adossés obligatoirement à un indicateur du dictionnaire, avancement calculé et non déclaré (STR-1) ; cascade avec consolidation sans double comptage (STR-2) ; initiatives sur le moteur de workflow et le chatter existants ; c-okr-card. Lancement de la démarche administrative du canal — prépare H9. | 5 | 2 |
| **S15** | Construction du budget | Saisie par axe et par période ; initialisation depuis un scénario de simulation ou une prévision publiée avec conservation de la référence source (STR-4) ; versions successives ; verrouillage opposable à tous les rôles et à l'API (STR-3). Mesure UC12. | 6 | 2,5 |
| **S16** | Suivi budgétaire et écarts | c-variance-table : réel / budget / prévision, écart en valeur et en pourcentage, seuil paramétrable ; test vérifiant l'identité des définitions d'indicateur employées de part et d'autre (STR-5) ; commentaire de gestion rattaché à la ligne et bloquant au-delà du seuil (STR-6). | 6 | 2,5 |
| **S17** | Revue, risques, tableau de bord de direction | Pack de revue généré, horodaté et figé, conservant valeurs, définitions et commentaires, consultable hors connexion (STR-7) ; cartographie des risques d'entreprise avec audit des réévaluations (STR-8) ; tableau de bord dirigeant à six tuiles. Mesure UC13. | 5 | 2 |

> Fin du bloc D — jalon J4 : la revue mensuelle de direction se prépare intégralement dans WideHalo. C'est le jalon le plus convaincant auprès d'un dirigeant.

### 14.6 Bloc E — WhatsApp (S18 à S21)

Bloc court parce que le moteur de notification existe depuis la Phase 1. Le risque n'est pas technique mais externe : règles du fournisseur qui évoluent, vérification administrative, coût variable.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S18** | Vérification des règles et adaptateur | Commence par une vérification directe de la documentation du fournisseur — lève H8, avant tout code. Adaptateur de canal branché sur le moteur de notification ; point de terminaison entrant avec vérification de signature ; bibliothèque de modèles avec statut d'approbation, variables, langues, catégorie et coût paramétré (WA-10). Vérification de la disponibilité du numéro — lève H9. | 6 | 2,5 |
| **S19** | Consentement, fenêtre, conversation | Consentement par tiers avec origine, date et révocation immédiate (WA-1, WA-2) ; contrôle de la fenêtre de service avec temps restant affiché et refus des envois libres hors fenêtre (WA-3) ; c-conversation intégré au chatter (WA-6) ; journal d'envoi avec statut et coût (WA-4). | 5 | 2 |
| **S20** | Usages sortants | Devis, facture, relance d'échéance, confirmation de commande, avis d'expédition, ticket de caisse dématérialisé, diffusion d'un pack de revue ; liens sécurisés à durée limitée plutôt que détail dans le message ; mise en file et reprise canal coupé (WA-7). Mesure UC14. | 6 | 2,5 |
| **S21** | Parcours entrant et garde-fous | Menu d'intentions déclarées sans génération libre (WA-8) ; chiffres issus des outils lecture seule du gateway avec les mêmes restrictions de rôle et de tenant (WA-9) ; plafond mensuel par tenant avec arrêt automatique et alerte préalable, limite de fréquence par destinataire (WA-5) ; tableau de bord de coût du canal. | 5 | 2 |

### 14.7 Bloc F — Durcissement et mise en production (S22)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S22** | Recette, durcissement, bascule | Recette des 38 critères BI / FOR / STR / WA ; campagne de mesure de performance de restitution en réseau bridé ; tests de fuite par agrégat rôle par rôle ; audit d'accessibilité des graphiques et des tableaux de bord ; vérification du registre des traitements et de l'information contractuelle sur le canal ; restauration de sauvegarde testée, entrepôt compris ; mesure d'adoption et SUS sur les parcours UC9 à UC14 ; mise en production. | 5 | 2 |

### 14.8 Répartition du travail entre l'humain et l'assistant IA

Le profil de la Phase 2 diffère sensiblement de celui de la Phase 1 : il y a beaucoup moins de composants répétitifs à produire et beaucoup plus de modélisation. Le gain apporté par l'assistance IA est donc structurellement plus faible, ce qui explique un rapport Jour-Homme sur Jour-Token moins favorable qu'en Phase 1.

| Type de tâche | Délégué à l'assistant | Reste à la charge de l'humain | Gain |
|---|---|---|---|
| **Écrans de restitution, tuiles, rapports dérivés de la couche sémantique** | Génération complète à partir des définitions d'indicateurs. | Choix des tuiles et de la hiérarchie visuelle — la cause d'échec d'un tableau de bord est de conception, pas de code. | Élevé |
| **Chargements, transformations, tests de rejeu et de réconciliation** | Implémentation et tests à partir du modèle dimensionnel validé. | Validation des réconciliations : un écart de quelques ariary révèle souvent une erreur de modélisation, pas un arrondi. | Élevé |
| **Adaptateur de canal, modèles de message, journal de coût** | Implémentation, réessais, tests de panne. | Lecture des règles du fournisseur et rédaction des modèles de message — texte envoyé à des clients au nom du client. | Moyen |
| **Modèle dimensionnel et dictionnaire d'indicateurs** | Implémentation après conception validée. | Intégralité de la conception. C'est un travail de contrôle de gestion : définir le chiffre d'affaires net, la marge, l'encours. Un dictionnaire plausible mais faux contamine les quatre modules à la fois. | Faible |
| **Méthode de prévision et interprétation de l'erreur** | Implémentation des modèles et du rétrotest. | Choix des mailles, arbitrage sur la saisonnalité, lecture du biais, décision de repli. Un modèle qui s'ajuste bien à l'historique et prédit mal est le piège classique. | Faible |
| **Droits à la restitution et prévention de la fuite par agrégat** | Implémentation et tests par rôle. | Conception du modèle de menaces et définition des mailles interdites par indicateur. | Faible |
| **Conformité du canal (consentement, minimisation, registre)** | Implémentation des contrôles. | Décision juridique et rédaction contractuelle. | Nul |

## 15. Estimation détaillée

Une capacité en baisse et un gain IA plus faible qu'en Phase 1

### 15.1 Hypothèses de l'estimation

- Un seul développeur, maîtrisant désormais le socle qu'il a construit en Phase 1, mais découvrant la modélisation dimensionnelle et la prévision statistique.
- **4,5 jours** de travail effectif de développement par semaine, contre 5 en Phase 1 : le support d'un produit en production consomme du temps qui n'était pas pris en compte précédemment.
- Les lots transverses (environnement, tests, CI/CD, documentation, gestion de projet) sont inclus dans les chiffres par sprint.
- La rationalisation du catalogue de rapports (H6) réduit le volume à porter. Si le sprint 1 conclut à un portage intégral, le bloc B passe de 4 à 6 sprints.
- Les démarches administratives du canal (H9) et la rédaction des modèles de message ne sont pas dans le chiffrage de développement : ce sont des tâches du client ou de l'éditeur en tant qu'entreprise.
- **[HYPOTHÈSE H11]** Les ratios entre effort classique et effort assisté sont désormais calibrés sur les mesures de la Phase 1, mais le profil de tâches diffère (davantage de modélisation, moins de composants). Le sprint 5 sert de point de recalibrage.

### 15.2 Synthèse par bloc

| Bloc | Sprints | J/H — voie classique | J-Token — génération | J/H — supervision humaine |
|---|---|---|---|---|
| **A — Cadrage et socle analytique** | S1–S5 | 33 | 14 | 11 |
| **B — Business Intelligence** | S6–S9 | 24 | 10 | 8 |
| **C — Forecast** | S10–S13 | 25 | 10,5 | 9 |
| **D — Strategy** | S14–S17 | 22 | 9 | 7 |
| **E — WhatsApp** | S18–S21 | 22 | 9 | 8 |
| **F — Durcissement et mise en production** | S22 | 5 | 2 | 2 |
| **Total Phase 2** | **22** | **131** | **54,5** | **45** |

### 15.3 Comparaison avec la Phase 1

La comparaison est instructive et mérite d'être explicite, car elle contredit une intuition courante — celle selon laquelle un projet accélère à mesure que le socle s'épaissit.

| Indicateur | Phase 1 | Phase 2 | Lecture |
|---|---|---|---|
| **Sprints** | 35 | 22 | Périmètre plus étroit et socle réutilisé. |
| **J/H par sprint** | 5,9 | 6,0 | Équivalent : la charge hebdomadaire ne baisse pas. |
| **Rapport J/H ÷ J-Token** | 2,30 | 2,40 | Gain IA légèrement plus faible : moins de composants répétitifs, plus de modélisation. |
| **Supervision ÷ J-Token** | 0,81 | 0,83 | Part de relecture humaine équivalente, concentrée sur le dictionnaire et la prévision. |
| **Nouveaux composants UI** | ~20 | 9 | Le rendement de l'investissement de la Phase 1 : la bibliothèque existante couvre l'essentiel. |
| **Capacité hebdomadaire retenue** | 5 j | 4,5 j | Support d'un produit en production. |

### 15.4 Trois scénarios

| Scénario | J/H classique | J-Token | Supervision | Durée calendaire | Ce qui le déclenche |
|---|---|---|---|---|---|
| **Optimiste** | 105 | 44 | 36 | 18 semaines | L'audit du sprint 1 permet de réduire fortement le catalogue ; l'historique se révèle suffisant pour une saisonnalité fiable ; le numéro professionnel est vérifié sans délai. |
| **Réaliste** | 131 | 54,5 | 45 | 22 semaines | Scénario de référence du plan de la section 14. |
| **Pessimiste** | 180 | 78 | 62 | 31 semaines | Le banc d'essai de volume impose un moteur analytique dédié (H7) ; le catalogue doit être porté intégralement ; l'historique est insuffisant et la prévision doit être revue ; la vérification administrative du canal bloque et impose un intermédiaire. |

### 15.5 Marges appliquées par type de tâche

| Type de tâche | Marge | Justification |
|---|---|---|
| **Écrans de restitution dérivés du socle, rapports, tuiles** | +10 à 20 % | Répétitif et bien cadré une fois la couche sémantique en place. |
| **Chargements, agrégats, réconciliation** | +30 à 50 % | La difficulté n'est pas le code mais la détection des écarts : on ne sait pas à l'avance quels cas particuliers l'opérationnel contient. |
| **Modèle dimensionnel et dictionnaire d'indicateurs** | +50 à 100 % | Forte incertitude : dépend d'arbitrages de gestion à obtenir auprès du client, souvent par itérations. Se découvre en rédigeant les définitions. |
| **Moteur de prévision et qualité statistique** | +50 à 100 % | Dépend de la profondeur et de la propreté de l'historique réel (H10), inconnues à la rédaction. |
| **Canal de messagerie** | +50 à 100 % | Deux inconnues externes : règles du fournisseur qui évoluent (H8) et délai administratif non maîtrisé (H9). |

## 16. Risques et plan de mitigation

Numérotation propre à la Phase 2

| Réf. | Risque | Impact | Prob. | Mitigation et signal d'alerte |
|---|---|---|---|---|
| **P2-R1** | Divergence de chiffres entre deux écrans, ou entre un rapport et la comptabilité. C'est le défaut qui tue un module décisionnel : une seule occurrence en comité de direction suffit à le disqualifier. | Critique | Élevée | Dictionnaire d'indicateurs unique, seul chemin d'accès aux données (12.3) ; contrôle de réconciliation bloquant à chaque rafraîchissement ; test de cohérence inter-écrans en CI (BI-1) ; rapprochement à l'ariary près des rapports reconstruits (BI-3). Signal : une seule divergence signalée par le comptable → arrêt des livraisons jusqu'à explication. |
| **P2-R2** | Le catalogue de rapports hérité s'avère redondant, incohérent ou largement inutilisé ; le porter tel quel industrialise l'incohérence. | Majeur | Élevée | Audit et arbitrage écrit dès le sprint 1 (H6), avec rationalisation assumée et budget de rapports vérifié en CI. Signal : si plus de 70 % du catalogue doit être porté, le bloc B passe à 6 sprints — décision à prendre au sprint 1, pas au sprint 8. |
| **P2-R3** | Performance analytique insuffisante sur une instance PostgreSQL unique partagée avec la charge transactionnelle. | Majeur | Moyenne | Banc d'essai au sprint 2 sur trois exercices simulés (H7) ; partitionnement et agrégats matérialisés dès la conception ; repli identifié sur un moteur analytique embarqué. Signal : tableau de bord au-delà de 3 s malgré les agrégats. |
| **P2-R4** | La prévision est jugée fausse par les utilisateurs, puis ignorée. Le module devient une fonctionnalité morte. | Majeur | Moyenne | Référence naïve toujours affichée (FOR-1) ; erreur publiée honnêtement par rétrotest et non par ajustement (FOR-2) ; ajustement humain autorisé, tracé et mesuré (FOR-6, FOR-7). Signal : moins de 30 % des séries battant la référence naïve → revoir la maille de prévision avant d'ajouter des modèles. |
| **P2-R5** | La prévision d'approvisionnement est attendue par le client mais non livrable sans la Phase 3. | Majeur | Élevée | Périmètre écrit dans le cahier des charges (2.4) et à reprendre dans l'offre commerciale. Ce risque se traite au contrat, pas en développement. |
| **P2-R6** | Blocage administratif du canal : numéro ou compte professionnel non vérifié dans les délais. | Moyen | Moyenne | Démarche engagée au sprint 14, quatre sprints avant le besoin (H9) ; repli sur un intermédiaire spécialisé (9.2) ; l'e-mail reste le canal par défaut, donc un blocage retarde une fonctionnalité sans bloquer la Phase 2. |
| **P2-R7** | Dérive du coût variable du canal : envoi en boucle, volume supérieur au contrat, changement tarifaire du fournisseur. | Moyen | Moyenne | Plafond mensuel par tenant appliqué techniquement avec arrêt automatique et alerte préalable, limite de fréquence par destinataire (WA-5) ; coûts paramétrés et non codés ; tableau de bord de coût. |
| **P2-R8** | Fuite de données personnelles vers un tiers établi hors de Madagascar, ou envoi à des destinataires non consentants. | Critique | Faible | Consentement vérifié à l'envoi et non à la configuration (WA-1) ; minimisation du contenu au profit de liens sécurisés à durée limitée ; écran énonçant les données qui sortent (WA-10) ; registre des traitements et information contractuelle vérifiés au sprint 22. |
| **P2-R9** | Fuite par agrégat : un rapport agrégé révèle une information interdite au rôle (rémunération déduite d'un agrégat filtré sur une personne, chiffre d'affaires global déduit par un commercial). | Majeur | Moyenne | Périmètre du rôle appliqué avant agrégation ; maille minimale déclarée par indicateur ; tests de restitution rôle par rôle et maille par maille (BI-6, section 6.1). |
| **P2-R10** | Les tableaux de bord et le budget deviennent un exercice formel que personne n'utilise. | Majeur | Moyenne | Six tuiles au maximum par rôle ; commentaire de gestion obligatoire seulement au-delà d'un seuil (STR-6) ; pack de revue figé (STR-7) ; budget initialisable depuis un scénario existant (STR-4). Mesure d'adoption en section 17.3. Signal : moins de 40 % des utilisateurs cibles consultant un tableau de bord hebdomadairement au jalon J2 → revue de conception avant d'engager le bloc C. |

## 17. Critères de recette et métriques de succès

Un module décisionnel se juge à son usage, pas à son périmètre

### 17.1 Recette fonctionnelle

La recette est constituée des critères numérotés de la section 13 : 10 critères Business Intelligence, 10 critères Forecast, 8 critères Strategy et 10 critères WhatsApp, soit **38 critères**, tous automatisés. La Phase 2 est reçue lorsque l'intégralité passe en intégration continue, sans exception tolérée.

### 17.2 Recette technique — barrières bloquantes

| Barrière | Vérification automatisée |
|---|---|
| **Budgets d'architecture** | Modèles ≤ 285, endpoints ≤ 840, écrans ≤ 180, écrans legacy = 0, rapports ≤ plafond fixé au sprint 1. |
| **Cohérence des chiffres** | Un jeu d'indicateurs témoins renvoie la même valeur sur tous les écrans et se rapproche des états comptables à l'ariary près. |
| **Intégrité du rafraîchissement** | Rejeu d'une période sans doublon ; contrôle de réconciliation au vert ; aucun chevauchement d'exécution. |
| **Absence de SQL exposé** | Aucun endpoint n'accepte de SQL ni de fragment de requête en entrée ; le moteur guidé est le seul chemin vers l'entrepôt. |
| **Droits à la restitution** | Aucun rapport ne restitue, même en agrégé, plus que ce que le rôle verrait en détail ; test par rôle et par maille. |
| **Isolation multi-tenant** | Rôle applicatif ni superutilisateur ni exempté de RLS ; policies actives sur l'entrepôt comme sur l'opérationnel. |
| **Consentement du canal** | Aucune voie applicative ne permet un envoi sans consentement enregistré et non révoqué. |
| **Plafonnement du coût** | Le plafond mensuel par tenant arrête effectivement les envois non critiques ; aucune règle tarifaire dans le code. |
| **Qualité de prévision** | Erreur mesurée par rétrotest et non par ajustement ; référence naïve calculée pour chaque série. |
| **Immutabilité du figé** | Un pack de revue et un budget verrouillé refusent toute modification, y compris par l'API et pour un administrateur. |
| **Performance de restitution** | Tableau de bord de six tuiles sous 3 s en profil réseau dégradé sur trois exercices d'historique. |
| **Sauvegarde** | Restauration réelle testée, entrepôt compris, dans les 30 jours. |

### 17.3 Métriques de succès

Les métriques d'expérience de la Phase 1 (SUS, temps par tâche, clics, facilité perçue) restent applicables sur les parcours UC9 à UC14. La Phase 2 y ajoute des métriques d'usage et de justesse, parce qu'un module décisionnel peut être parfaitement ergonomique et complètement inutilisé.

| Métrique | Protocole | Cible Phase 2 | Seuil de rattrapage |
|---|---|---|---|
| **Cohérence des chiffres** | Jeu d'indicateurs témoins comparé sur tous les écrans et aux états comptables. | Zéro divergence | Toute divergence → arrêt des livraisons |
| **Adoption des tableaux de bord** | Part des utilisateurs cibles consultant un tableau de bord au moins une fois par semaine. | ≥ 70 % | < 40 % au jalon J2 → revue de conception |
| **Autonomie de restitution** | Part des rapports consultés issus du constructeur self-service ; nombre de demandes de rapport adressées au support. | ≥ 30 % en self-service | Aucune baisse des demandes au support |
| **Justesse de prévision** | Erreur pondérée par rétrotest sur les familles principales ; part des séries battant la référence naïve. | ≥ 70 % des séries battent le naïf | < 30 % → revoir la maille de prévision |
| **Apport de l'ajustement humain** | Erreur de la prévision ajustée comparée à la statistique sur périodes échues. | Ajusté meilleur que statistique | Ajusté systématiquement moins bon → accompagnement des contributeurs |
| **Préparation de la revue** | Temps de préparation du pack de revue mensuelle, mesuré avant et après. | – 50 % | < – 20 % → revoir le pack |
| **Efficacité du canal** | Taux de livraison et de lecture comparé à l'e-mail ; effet sur le délai moyen de règlement après relance. | Supérieur à l'e-mail | Équivalent ou inférieur → revoir les modèles de message |
| **Maîtrise du coût** | Consommation mensuelle par tenant face au plafond. | Aucun dépassement non alerté | Un seul dépassement silencieux → incident majeur |
| **SUS** | Même protocole que la Phase 1, sur les parcours UC9 à UC14. | ≥ 80 | < 68 → revue de conception |

**Pourquoi l'adoption figure parmi les critères et non parmi les espérances.** Un module de restitution peut passer 38 critères d'acceptation sur 38 et n'être ouvert par personne. Contrairement à une facture ou à une caisse, dont l'usage est imposé par le processus, un tableau de bord n'est utilisé que s'il est utile. C'est pourquoi la mesure d'adoption au jalon J2 est un point de décision réel : elle intervient avant l'engagement des blocs C et D, alors qu'il est encore temps de revoir la conception.

### 17.4 Conditions de mise en production

1. Les 38 critères d'acceptation de la section 13 passent en intégration continue.
2. Les douze barrières techniques de la section 17.2 sont au vert.
3. Zéro divergence constatée sur le jeu d'indicateurs témoins, et rapprochement validé par le comptable entre les rapports financiers et les états PCG 2005.
4. Le registre des traitements et l'information contractuelle du client sur le canal de messagerie sont établis, et le plafonnement de coût est actif.
5. Une restauration de sauvegarde a été réalisée et vérifiée, entrepôt compris.
6. L'adoption mesurée atteint au minimum le seuil de rattrapage, et le score SUS est maintenu au niveau de la Phase 1.

## 18. Annexes

Glossaire, références, suites

### 18.1 Glossaire — termes propres à la Phase 2

Le glossaire de la Phase 1 (PCG 2005, SYSCOHADA, OECFM, RLS, strangler pattern, chatter, launchpad, function calling, Jour-Token, patronnage, gradation…) reste applicable. Ne sont définis ici que les termes introduits par la Phase 2.

| Terme | Définition |
|---|---|
| **Entrepôt de données** | Copie réorganisée des données opérationnelles, structurée pour l'analyse plutôt que pour la saisie. Ici, un schéma séparé dans la même base PostgreSQL. |
| **Schéma en étoile** | Organisation où des tables de faits (les événements mesurés) sont entourées de tables de dimensions (les axes d'analyse). |
| **Dimension conforme** | Dimension partagée par plusieurs faits, ce qui permet de croiser des mesures d'origines différentes sur un même axe. Condition de l'extension à la Phase 3 sans reprise. |
| **Fait** | Ligne mesurable de l'entrepôt : une ligne de facture, un règlement, une ligne d'écriture. Stockée à la maille du document, jamais agrégée. |
| **Grain** | Niveau de détail auquel un fait est stocké. Un grain trop grossier interdit définitivement l'exploration du détail. |
| **Vue matérialisée** | Résultat de requête stocké physiquement et rafraîchi périodiquement. C'est ce qui tient l'objectif de trois secondes. |
| **Rafraîchissement incrémental** | Chargement des seules lignes créées ou modifiées depuis la dernière exécution, par opposition au rechargement complet. |
| **Couche sémantique** | Vocabulaire métier interposé entre l'utilisateur et l'entrepôt : mesures et dimensions déclarées. Seul chemin d'accès aux données analytiques dans WideHalo. |
| **Dictionnaire d'indicateurs** | Ensemble gouverné des mesures : nom, définition, formule, propriétaire, axes autorisés, rôles, version. Un indicateur, une définition, dans tout le produit. |
| **Maille** | Niveau d'agrégation d'une restitution. Une maille minimale peut être interdite pour éviter la fuite par agrégat. |
| **Fuite par agrégat** | Déduction d'une information interdite à partir de chiffres agrégés autorisés — par exemple un salaire lu dans un agrégat filtré sur une seule personne. |
| **Rétrotest** | Évaluation d'un modèle de prévision sur des périodes passées qu'il n'a pas servi à apprendre. Seule mesure d'erreur honnête. |
| **Référence naïve saisonnière** | Prévision consistant à reprendre la valeur de la même période de l'année précédente. Étalon minimal : un modèle qui ne la bat pas est inutile. |
| **Biais** | Tendance d'une prévision à se tromper toujours dans le même sens. Plus utile en gestion que l'erreur moyenne, car il se corrige. |
| **Prévision collaborative** | Prévision statistique corrigée par la connaissance terrain, avec traçabilité et mesure de l'apport de la correction. |
| **Objectif et résultat clé** | Intention qualitative assortie de mesures chiffrées d'atteinte. Dans WideHalo, tout résultat clé est adossé à un indicateur du dictionnaire. |
| **Pack de revue** | Document de décision généré à date, figé et horodaté, conservant les valeurs, les définitions et les commentaires en vigueur à sa génération. |
| **Modèle de message** | Gabarit de message pré-approuvé par le fournisseur du canal, obligatoire pour initier une conversation. Comporte des variables et une langue. |
| **Fenêtre de service** | Période ouverte par un message du destinataire, pendant laquelle la réponse de l'entreprise est libre. En dehors, seul un modèle approuvé passe. |
| **Consentement (opt-in)** | Accord préalable et révocable du destinataire à recevoir des messages. Vérifié à chaque envoi, pas à la configuration. |

### 18.2 Documents de référence

- **Cahier des charges WideHalo v3 — Phase 1** : socle d'expérience, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, Patronnage, IA. Document prérequis de celui-ci ; ses décisions d'architecture ne sont pas rediscutées ici.
- INVENTAIRE_EXISTANT.md — produit au sprint 1 de la Phase 1 ; reste le point de vérité sur l'existant.
- **Audit du catalogue de rapports** — à produire au sprint 1 de la Phase 2 ; contient l'arbitrage rapport par rapport et fixe le budget de rapports.
- **Dictionnaire d'indicateurs** — livrable vivant, produit au sprint 3 et maintenu ensuite. C'est le document de référence métier de toute la Phase 2.
- **Documentation du fournisseur du canal de messagerie** — à vérifier au sprint 18 avant implémentation (H8).
- **Cahier des charges Phase 3** — à produire : Achats/Import et CREDOC, Stock et entrepôt, Production, Qualité/HACCP, Paie.

### 18.3 Suites immédiates

| Action | Échéance | Pourquoi elle passe avant le développement |
|---|---|---|
| **Vérifier que la Phase 1 est stabilisée** | Avant le sprint 1 | Un module décisionnel construit sur des données opérationnelles instables produit des chiffres faux, et un chiffre faux en comité de direction coûte des mois de crédibilité. |
| **Auditer et rationaliser le catalogue de rapports** | Sprint 1 | Porter 91 rapports hétérogènes sur la couche sémantique reviendrait à industrialiser l'incohérence. L'arbitrage conditionne le dimensionnement du bloc B. |
| **Obtenir les définitions d'indicateurs auprès du client** | Sprints 1 à 3 | C'est le seul travail de la Phase 2 qui ne peut être ni délégué à l'assistant IA ni décidé par l'éditeur. Une définition ajoutée tard oblige à reprendre rapports, prévisions et écarts. |
| **Mesurer la ligne de base des parcours UC9 à UC14** | Sprint 1 | Sans mesure de la pratique actuelle (tableur, reprises manuelles), le gain de la Phase 2 restera une impression. |
| **Engager la démarche administrative du canal** | Sprint 14 | Le délai de vérification n'est pas maîtrisé par l'éditeur (H9). L'engager quatre sprints avant le besoin évite qu'un blocage administratif ne devienne un retard projet. |
| **Rédiger le cahier des charges de la Phase 3** | Après le jalon J2 | Le modèle dimensionnel doit être éprouvé avant d'y ajouter les faits de stock, d'achat et de production. |

> Fin du cahier des charges WideHalo v3 — Phase 2. Ce document suppose la Phase 1 livrée et n'en respécifie aucune décision. Les critères d'acceptation de la section 13 sont écrits pour être traduits en tests, et le plan de la section 14 pour être suivi sprint par sprint. La Phase 3 (Achats/Import et CREDOC, Stock et entrepôt, Production, Qualité/HACCP, Paie) fera l'objet d'un document distinct, dont le moteur de prévision et le modèle dimensionnel livrés ici constituent déjà les points d'accroche.
