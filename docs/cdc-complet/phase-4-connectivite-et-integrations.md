# WideHalo v3 — Cahier des charges Phase 4

*Connectivité, flux et écosystème tiers de l'ERP WideHalo*

**PHASE 4 — Socle de flux • API publique et webhooks • Conformité e-facture**

*Encaissement mobile et rapprochement • Flux bancaires • Bureautique et stockage • Commerce • Console de flux*

| Rubrique | Valeur |
|---|---|
| PROJET | WideHalo — ERP PME |
| DOCUMENT | Cahier des charges |
| VERSION | 3.0 — Phase 4 |
| MAÎTRE D'OUVRAGE | Life MDG |
| PRÉREQUIS | Phases 1 à 3 en production |
| DATE | Septembre 2026 |
| MODE DE DÉVELOPPEMENT | Solo assisté IA (Claude Code) |
| DURÉE PHASE 4 | 34 sprints — deux vagues |
| STATUT | Pour validation |

- **1. Résumé exécutif**
  - Les sept décisions structurantes
  - Périmètre de ce document
- **2. Contexte, objectifs et périmètre**
  - 2.1 Ce dont la Phase 4 hérite
  - 2.2 Pourquoi le flux passe avant le logiciel
  - 2.3 Objectifs de la Phase 4
  - 2.4 Position dans la trajectoire produit
  - 2.5 Périmètre inclus
  - 2.6 Périmètre exclu
- **3. Analyse de l'écosystème tiers**
  - 3.1 Méthode de classement et unité de mesure
  - 3.2 Palier A — Bureautique et productivité
  - 3.3 Palier B — Messagerie conversationnelle
  - 3.4 Palier C — Argent et flux financiers
  - 3.5 Palier D — Conformité et flux réglementaires
  - 3.6 Palier E — Commerce et canaux de vente
  - 3.7 Palier F — Automatisation et orchestration
  - 3.8 Palier G — Terrain, matériel et flux locaux
  - 3.9 Matrice de priorisation
- **4. Opérations attendues sur les liaisons**
  - 4.1 Les huit opérations canoniques
  - 4.2 Les quatre modes de déclenchement
  - 4.3 Les sept axes de personnalisation
  - 4.4 Ce que « automatisable » n'autorise pas
- **5. Utilisateurs cibles et cas d'usage**
  - 5.1 Trois profils nouveaux
  - 5.2 Parcours de référence de la Phase 4
- **6. Contraintes du projet**
  - 6.1 Hypothèses ouvertes à lever
- **7. Architecture applicative**
  - 7.1 Chaîne de flux — Phase 4
  - 7.2 Couche présentation
  - 7.3 Couche logique métier
  - 7.4 Couche données
  - 7.5 Couche intégration
  - 7.6 Infrastructure
  - 7.7 Couche transverse
- **8. Sécurité**
  - 8.1 Secrets et identifiants de tiers
  - 8.2 Surface entrante : webhooks et API publique
  - 8.3 Non-répudiation des échanges
  - 8.4 Confinement du copilote, étendu aux flux
- **9. Gouvernance des données et souveraineté**
  - 9.1 Le consentement de sortie
  - 9.2 Classification des données sortantes
  - 9.3 Rétention des charges utiles
  - 9.4 Cadre malgache et transferts
- **10. UX et confort d'exploitation**
  - 10.1 Le problème d'interface propre à la Phase 4
  - 10.2 Neuf composants nouveaux
  - 10.3 Le vocabulaire de l'échec
- **11. Scalabilité**
  - 11.1 Budgets d'architecture révisés
- **12. Choix technologiques**
  - 12.1 Orchestration : bus interne ou plateforme tierce
  - 12.2 Encaissement mobile : opérateur direct ou agrégateur
  - 12.3 Raccordement fiscal : direct ou par tiers de confiance
  - 12.4 Briques confirmées sans réexamen
- **13. Socle de connectivité et modèle de flux**
  - 13.1 L'échange comme écriture unique
  - 13.2 Entités du socle
  - 13.3 Cycle de vie d'un échange
  - 13.4 Idempotence, corrélation et rejeu
  - 13.5 Extension du modèle dimensionnel
- **14. Spécifications fonctionnelles — Phase 4**
  - 14.1 F1 — Socle de flux et registre d'échange
  - 14.2 F2 — API publique, webhooks et quotas
  - 14.3 F3 — Conformité e-facture et clearance
  - 14.4 F4 — Encaissement mobile et rapprochement
  - 14.5 F5 — Flux bancaires et trésorerie
  - 14.6 F6 — Bureautique, stockage et calendrier
  - 14.7 F7 — Commerce et canaux de vente
  - 14.8 F8 — Messagerie étendue
  - 14.9 F9 — Console de flux et gouvernance
- **15. Modèle économique des connecteurs**
  - 15.1 Trois régimes tarifaires
  - 15.2 Règles de facturation à l'usage
  - 15.3 Ce que le régime tarifaire impose au produit
- **16. Plan de développement — sprints hebdomadaires**
  - 16.1 Ordonnancement et dépendances
  - 16.2 Blocs A à I
  - 16.3 Répartition du travail humain / assistant
- **17. Estimation détaillée**
  - 17.1 Hypothèses de l'estimation
  - 17.2 Synthèse par bloc
  - 17.3 Comparaison avec les Phases 1 à 3
  - 17.4 Trois scénarios
- **18. Risques et plan de mitigation**
- **19. Critères de recette et métriques de succès**
  - 19.1 Recette fonctionnelle
  - 19.2 Recette technique — barrières bloquantes
  - 19.3 Métriques de succès
  - 19.4 Conditions de mise en production
- **20. Annexes**
  - 20.1 Glossaire — termes propres à la Phase 4
  - 20.2 Sources de l'analyse de marché
  - 20.3 Suites immédiates

## 1. Résumé exécutif

*Le produit change de nature : il cesse d'enregistrer, il commence à transporter*

Les Phases 1 à 3 ont construit un système d'enregistrement complet : la vente, l'écriture comptable, l'encaissement, la restitution, la prévision, le stock, la production, la qualité et la paie. Tout y entre par une saisie et en sort par un document. La Phase 4 rompt avec ce principe : elle fait de WideHalo un point de passage. La facture n'est plus imprimée, elle est transmise à une plateforme fiscale qui la valide ou la rejette. L'encaissement n'est plus constaté, il est initié puis confirmé par un opérateur de monnaie électronique. Le relevé bancaire n'est plus lu, il est ingéré et rapproché. Le rapport n'est plus exporté, il est déposé là où le client travaille déjà.

**Ce changement de nature est la vraie décision de cette phase.** Un logiciel qui stocke ce qu'on lui dicte est remplaçable en un week-end de reprise de données. Un logiciel par lequel passent réellement l'argent, la preuve fiscale et le document contractuel ne se remplace pas sans interrompre l'exploitation. C'est la raison pour laquelle la maîtrise des flux précède, dans ce document, la mise à disposition des fonctionnalités : le registre d'échange est construit et testé avant qu'un seul connecteur ne soit écrit.

### Les sept décisions structurantes

1. **Le registre d'échange est construit avant le premier connecteur.** Tout échange entrant ou sortant — soumission fiscale, initiation de paiement, dépôt de fichier, appel d'API entrant, notification reçue — est une ligne de la même table, orientée, datée, empreintée, corrélée à sa pièce métier et rejouable. C'est au flux ce que le mouvement est au stock en Phase 3 : la seule vérité. Un adaptateur qui n'écrit pas dans le registre n'est pas un connecteur, c'est une fuite. Un test d'intégration continue échoue si un appel sortant contourne le registre.
2. **Un connecteur est un adaptateur de protocole, jamais un module.** Huit opérations canoniques et quatre modes de déclenchement couvrent l'intégralité des liaisons identifiées en section 3. Ajouter un tiers doit consister à écrire une correspondance de champs, une politique d'authentification et une traduction d'erreurs — pas des écrans, pas un cycle de vie, pas une table. Le jour où cette règle est violée, le catalogue de connecteurs devient ingérable par une personne seule, exactement comme le catalogue de rapports l'aurait été sans le plafond posé en Phase 2.
3. **L'ordre de priorité est : obligation, argent, document, confort.** Il n'est pas négociable et il ne suit pas l'enthousiasme des utilisateurs. Le décret malgache du 2 juillet 2025 instituant la facturation électronique obligatoire pour les transactions entre entreprises et avec le secteur public fait du raccordement à la plateforme fiscale centrale le seul connecteur dont l'absence rendra le produit invendable. Tout le reste est un avantage concurrentiel ; celui-là est un droit d'exister.
4. **WideHalo n'est pas un opérateur de paiement et ne le deviendra pas.** Il initie une intention de paiement, en suit l'état et la rapproche d'une pièce comptable. Les fonds transitent du client final vers le compte du tenant, jamais par un compte de l'éditeur. Cette limite est d'abord juridique — détenir des fonds pour le compte de tiers relève d'un agrément — et elle a une conséquence de conception : le rapprochement, et non l'encaissement, est le cœur du bloc financier.
5. **Une API publique stable et des webhooks valent mieux que quarante connecteurs.** Le catalogue natif est plafonné à douze adaptateurs. Au-delà, le produit expose une surface documentée, versionnée et testée, et laisse l'orchestration à l'outil que le client utilise déjà. Un moteur d'automatisation auto-hébergeable est recommandé et documenté, mais il n'est pas embarqué : le maintenir serait un second produit.
6. **Tout échange porte un coût imputé et un plafond opposable.** Le compteur de coût par tenant introduit en Phase 2 pour la messagerie devient transverse et s'applique au message, au paiement, à la soumission fiscale et à l'appel d'API sortant. Aucun tarif n'est écrit dans le code : les grilles rejoignent la table de paramètres versionnés livrée en Phase 1. Un plafond atteint suspend le connecteur et notifie, il ne fait pas silencieusement échouer.
7. **Aucun flux sortant n'est actif par défaut, et l'ERP reste entier sans aucun d'eux.** La règle posée en Phase 1 et reconduite deux fois cesse d'être une déclaration d'intention : elle devient une barrière de recette. Un scénario de recette coupe l'intégralité des connecteurs et vérifie que les parcours des Phases 1 à 3 restent exécutables de bout en bout, en mode saisie.

**Deux vagues, articulées sur un calendrier que l'éditeur ne maîtrise pas.** La **vague 4A** — socle de flux, API publique et webhooks, conformité e-facture — est mise en production au jalon J4, au sprint 16. La **vague 4B** — encaissement mobile, flux bancaires, bureautique, commerce, console de flux — suit. Le découpage ne répond pas ici à un souci de trésorerie de projet comme en Phase 3, mais à une contrainte externe : le délai de mise en conformité court à partir de la mise en service de la plateforme fiscale centrale, dont la date n'est pas connue. La vague 4A doit être prête avant cet événement, pas après.

### Périmètre de ce document

Ce document couvre exclusivement la Phase 4. Il suppose les Phases 1 à 3 livrées et stabilisées : socle d'expérience utilisateur, moteur de vues configurables, data grid, chatter, moteur de workflow déclaratif, moteur de notification et de canal, référentiel comptable PCG 2005, paramètres réglementaires versionnés, POS et protocole hors ligne, entrepôt analytique en étoile, couche sémantique, moteur de prévision, gateway IA, socle d'inventaire et mouvement unique, dossier d'import et CREDOC, production, qualité et paie sont des acquis. Aucune de leurs décisions d'architecture n'est rediscutée ; elles sont rappelées uniquement là où la Phase 4 s'y raccorde. Ce que la Phase 4 laisse ouvert — localisation OHADA complète, consolidation multi-sociétés, gestion des ressources humaines élargie, place de marché de connecteurs tiers — relève de la feuille de route produit et non d'une phase déjà cadrée.

## 2. Contexte, objectifs et périmètre

*Ce que la Phase 4 hérite, et pourquoi elle ne pouvait pas venir plus tôt*

### 2.1 Ce dont la Phase 4 hérite

La Phase 4 est la première qui n'ajoute presque aucun domaine métier. Elle ajoute un moyen de transport à des domaines déjà modélisés. Neuf acquis sont directement réutilisés, et trois d'entre eux — le moteur de notification abstrait, le compteur de coût par tenant et le journal d'audit à valeur opposable — ont été conçus dans les phases précédentes en anticipant précisément cet usage.

| Acquis des Phases 1 à 3 | Usage en Phase 4 |
|---|---|
| **Moteur de notification et de canal abstrait (Phase 1, étendu en Phase 2)** | Le modèle destinataire / gabarit / canal / statut d'envoi / réessai devient le patron du connecteur sortant. La messagerie professionnelle en était le premier adaptateur ; elle en devient un parmi neuf, sans reprise du modèle. |
| **Compteur de coût et plafonnement par tenant (Phase 2)** | Généralisé à tous les échanges facturés à l'usage. Le mécanisme d'imputation, d'agrégation et de plafond existe ; seules les catégories de coût sont nouvelles. |
| **Paramètres réglementaires versionnés (core_regulatory_parameter, Phase 1)** | Porte les grilles tarifaires des tiers, les formats de fichier réglementaires, les seuils d'assujettissement et les dates d'entrée en vigueur des obligations. Un calendrier fiscal qui glisse est un paramètre, pas une version. |
| **Moteur de workflow déclaratif (Phase 1)** | Les transitions de document deviennent des déclencheurs d'échange : « facture validée » déclenche la soumission fiscale, « commande confirmée » déclenche l'accusé fournisseur. Aucun code d'orchestration nouveau. |
| **Journal d'audit à valeur opposable (Phase 3)** | Le statut de pièce opposable acquis pour la libération de lot et le bulletin publié s'étend à la preuve de soumission et à l'accusé de réception d'un tiers. Les exigences d'intégrité de la Phase 3 sont réutilisées telles quelles. |
| **Protocole hors ligne et file de saisie (Phases 1 et 3)** | La file de réconciliation terrain et le protocole de numérotation préfixée servent une quatrième fois, pour la file d'échanges en attente de tiers indisponible. |
| **Gateway IA à liste blanche (Phase 1, étendu en Phases 2 et 3)** | Modèle de confinement réutilisé pour la surface API publique : liste blanche déclarée, portées par rôle, journalisation systématique. Ce qui a été construit pour brider un modèle de langage bride tout aussi bien un client tiers. |
| **Entrepôt en étoile et dictionnaire d'indicateurs (Phase 2)** | Accueille les faits d'échange : volumétrie, taux de succès, latence, coût. La supervision des flux est un tableau de bord gouverné, pas un écran de logs. |
| **Dossier d'import, CREDOC et échanges documentaires (Phase 3)** | Les statuts saisis manuellement en Phase 3 deviennent, là où un tiers le permet, des statuts alimentés par échange. Le modèle ne change pas ; sa source change. |

### 2.2 Pourquoi le flux passe avant le logiciel

La proposition qui structure cette phase est empruntée à ce que l'on observe aujourd'hui dans l'édition de logiciel en service : **la fonctionnalité se copie, le flux ne se copie pas.** Deux ERP peuvent proposer la même facturation, le même stock et la même paie ; ils ne peuvent pas être simultanément celui par lequel la facture est transmise à l'administration, celui qui reçoit la notification de paiement et celui qui a rapproché le relevé. La position sur le flux est exclusive, elle est constatée par des tiers, et elle produit un historique que le concurrent ne détient pas.

Cette proposition a trois conséquences directes sur la conception, et elles expliquent l'ordre des blocs du plan de la section 16.

- **Première conséquence : le registre précède les connecteurs.** Construire le registre d'échange après avoir écrit trois adaptateurs conduit à trois formats de journal, trois politiques de réessai et trois manières de dire qu'un envoi a échoué. Le bloc A ne livre aucune connexion visible par le client ; il livre la table sans laquelle les huit blocs suivants coûteraient chacun deux sprints de plus.
- **Deuxième conséquence : la réconciliation prime sur l'exécution.** Initier un paiement est facile ; savoir avec certitude, trois jours plus tard, quelle facture il solde ne l'est pas. La valeur d'un connecteur financier tient à sa capacité à fermer la boucle — intention, notification, écriture, lettrage — et non à la beauté du bouton qui l'ouvre. Le chiffrage du bloc D reflète ce déséquilibre.
- **Troisième conséquence : la sortie doit rester réversible.** Un produit qui capte les flux est aussi un produit qui peut enfermer. La contrepartie éthique et commerciale de la position acquise est une garantie de sortie explicite : export intégral, format documenté, aucune donnée de flux inaccessible au client. Cette garantie est une exigence de recette, pas un argument marketing.

**Le flux est aussi ce qui rend le produit fragile.** Le raisonnement ci-dessus a un revers qu'il serait malhonnête de ne pas écrire : chaque flux capté est une panne dont l'éditeur devient responsable aux yeux du client, même quand elle vient du tiers. Une plateforme fiscale indisponible un 15 du mois, un opérateur de monnaie électronique qui change un format sans préavis, une clé qui expire un dimanche — ce sont désormais des incidents WideHalo. C'est la raison pour laquelle la règle de dégradation en saisie manuelle, héritée de la Phase 1, n'est pas assouplie mais durcie : elle est la seule protection d'un éditeur seul contre la responsabilité qu'il vient d'accepter.

### 2.3 Objectifs de la Phase 4

| Objectif | Énoncé | Critère de vérification |
|---|---|---|
| **O1 — Conformité transactionnelle** | Émettre, transmettre, faire valider et archiver une facture selon un dispositif de contrôle continu, sans réécriture du module Sales. | Une facture validée produit une soumission, un verdict et un archivage traçables ; le rejet est actionnable par l'utilisateur. |
| **O2 — Maîtrise du flux d'argent** | Initier un encaissement mobile et le rapprocher automatiquement de la pièce qui l'a motivé, sans intervention comptable dans le cas nominal. | Taux de rapprochement automatique mesuré et publié ; aucun encaissement sans pièce de contrepartie. |
| **O3 — Ouverture gouvernée** | Exposer une API publique et des webhooks utilisables par un intégrateur tiers sans accès à la base ni contournement de la logique métier. | Surface déclarée, versionnée, testée ; aucun endpoint hors liste blanche accessible par jeton client. |
| **O4 — Continuité sans tiers** | Garantir que l'ERP reste intégralement exploitable, connecteurs coupés. | Scénario de recette « tout coupé » exécuté sur les parcours des Phases 1 à 3. |
| **O5 — Coût gouverné** | Rendre visible et plafonnable le coût variable de chaque flux, par tenant et par catégorie. | Aucun tarif dans le code ; plafond atteint = suspension notifiée, jamais échec silencieux. |
| **O6 — Soutenabilité solo** | Absorber un écosystème mouvant sans que le nombre d'adaptateurs ne dépasse la capacité d'entretien d'une personne. | Plafond de douze connecteurs vérifié en intégration continue ; zéro adaptateur spécifique à un client. |

### 2.4 Position dans la trajectoire produit

| Phase | Modules | Rôle | Statut |
|---|---|---|---|
| **Phase 1** | Socle UX, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, Patronnage, IA | Rendre le produit utilisable et conforme. | Prérequis |
| **Phase 2** | Business Intelligence, Forecast, Strategy, canal de messagerie | Rendre le produit pilotable et communicant. | Prérequis |
| **Phase 3** | Stock et entrepôt, Achats / import / CREDOC, Production, Qualité et HACCP, Paie, extension Forecast | Couvrir le flux physique et le personnel : couverture ERP complète. | Prérequis |
| **Phase 4** | Socle de flux, API publique, conformité e-facture, encaissement mobile, flux bancaires, bureautique, commerce, console de flux | Rendre le produit connecté et opposable : faire passer les flux par lui plutôt qu'à côté de lui. | Objet de ce document |
| **Au-delà** | Localisation OHADA, consolidation multi-sociétés, RH élargies | Extension géographique et fonctionnelle, par paramétrage des moteurs existants. | Feuille de route |

### 2.5 Périmètre inclus

- **Socle de flux** : registre d'échange unique, liaisons paramétrées, correspondances de champs déclaratives, planification, déclencheurs sur transition de workflow, file d'attente et réessai avec disjoncteur, idempotence, corrélation, rejeu supervisé, journal d'incident.
- **API publique et webhooks** : surface REST versionnée et documentée en OpenAPI, clés par tenant avec portées et quotas, webhooks sortants avec signature et rejeu, bac à sable, journal d'appel, plafonnement par jeton.
- **Conformité e-facture** : abstraction de dispositif à contrôle continu — préparation du document normalisé, soumission, attente de verdict, réception du sceau et de son identifiant, apposition sur la représentation lisible, archivage à durée réglementaire, gestion du rejet, de l'annulation et de l'avoir, mode d'attente lorsque la plateforme est indisponible.
- **Encaissement mobile et rapprochement** : intention de paiement, lien et code à barres bidimensionnel de règlement, réception de notification, rapprochement automatique avec la facture ou le ticket de caisse, écriture comptable de contrepartie, gestion des doublons et des paiements orphelins, remboursement par contre-écriture.
- **Flux bancaires** : import de relevé multi-format, moteur de règles de rapprochement, lettrage assisté, production et export d'ordres de virement, suivi de l'état de remise, réconciliation de la caisse et des comptes d'attente.
- **Bureautique, stockage et calendrier** : dépôt de documents et d'archives dans un espace de stockage du client, export vivant vers une feuille de calcul, envoi de courriel par délégation authentifiée plutôt que par serveur d'envoi, publication d'événements d'exploitation dans un agenda.
- **Commerce et canaux de vente** : publication du catalogue et des disponibilités vers une boutique en ligne, ingestion des commandes, retour de statut d'expédition, avec un connecteur générique par fichier pour les canaux non couverts.
- **Messagerie étendue** : mise à niveau du canal livré en Phase 2 sur le modèle tarifaire au message, extension aux notifications de flux et aux accusés de réception.
- **Console de flux et gouvernance** : tableau de bord des échanges, coûts et plafonds, consentements de sortie, catalogue des connecteurs et de leurs états, rejeu supervisé, export intégral de garantie de sortie.

### 2.6 Périmètre exclu

Un périmètre sans exclusions explicites dérive. Les points suivants sont volontairement hors Phase 4 et doivent être repris tels quels dans l'offre commerciale.

- **Détention de fonds pour compte de tiers.** WideHalo n'ouvre pas de compte de cantonnement, n'agrège pas les encaissements de ses clients et ne reverse rien. L'agrément que cela suppose n'est ni recherché ni budgété.
- **Statut de plateforme de dématérialisation certifiée.** Tant qu'un régime d'opérateur agréé n'existe pas dans le droit applicable, WideHalo est un émetteur qui se raccorde, pas un intermédiaire qui certifie pour autrui.
- **Autorité de certification.** Le produit consomme un certificat de signature électronique fourni par le client ou par un prestataire ; il n'en émet pas et n'en gère pas le cycle de vie au-delà de l'alerte d'expiration.
- **Échange de données informatisé traditionnel** — messages normalisés de type EDIFACT ou X12, transport AS2, réseaux à valeur ajoutée. Aucun client visé ne l'exige, et la charge d'exploitation serait sans commune mesure avec le bénéfice.
- **Agrégation bancaire par extraction de page.** Les relevés sont fournis par le client ou par un canal contractuel. Aucune authentification bancaire n'est stockée.
- **Interface machine avec le système douanier** — reconduite de l'exclusion de la Phase 3 (H15). Le dossier d'import reste documentaire.
- **Éditeur visuel de scénarios pour l'utilisateur final.** La personnalisation est déclarative et bornée aux sept axes de la section 4.3. Construire un atelier d'automatisation revient à construire un second produit.
- **Place de marché de connecteurs développés par des tiers**, avec exécution de code externe dans l'instance. Le plafond de douze adaptateurs natifs et l'API publique tiennent lieu de réponse.
- **Synchronisation bidirectionnelle permanente d'un référentiel avec un tiers.** Un sens fait autorité par liaison, déclaré et vérifié. La fédération de données de référence n'est pas au programme.
- **Interrogation directe de la base par un outil tiers et génération de requêtes par un modèle de langage.** Exclusion de principe reconduite depuis la Phase 1, désormais également opposable aux clients de l'API publique.

**Trois travaux que la Phase 4 impose au client, et qui ne sont pas du développement.** Premièrement, l'enrôlement auprès des tiers — habilitation fiscale, contrat marchand auprès d'un opérateur de monnaie électronique, déclaration d'application — est une démarche administrative dont le délai n'appartient ni à l'éditeur ni au client, et qui doit être engagée plusieurs semaines avant le sprint qui la consomme. Deuxièmement, la qualité du référentiel tiers devient bloquante : un identifiant fiscal absent ou faux, qui n'empêchait qu'une impression jusqu'ici, empêchera désormais une validation. Troisièmement, la reprise de l'historique de rapprochement bancaire doit être arrêtée à une date, faute de quoi le lettrage démarre sur un solde qui ne se justifie pas. Ces trois travaux relèvent du client, avec un accompagnement à chiffrer séparément du développement. Les inscrire dans le contrat évite qu'ils ne soient découverts au sprint 11, quand le connecteur sera prêt et l'habilitation non demandée.

## 3. Analyse de l'écosystème tiers

*Ce à quoi il faut se brancher, dans l'ordre où les clients le rencontrent*

### 3.1 Méthode de classement et unité de mesure

Le choix des connecteurs ne se décide pas à la notoriété d'un éditeur mais au nombre d'utilisateurs professionnels que le client de WideHalo côtoie réellement. Une plateforme installée chez des millions d'entreprises dans le monde mais absente du tissu malgache ne justifie pas un adaptateur ; un service utilisé par la moitié des adultes du pays le justifie, même s'il est inconnu ailleurs. L'analyse est donc conduite sur trois mailles simultanées, et un tiers n'est retenu que s'il pèse sur au moins deux d'entre elles ou s'il est imposé par la loi sur la troisième.

| Maille | Ce qu'elle mesure | Ce qu'elle sert à décider |
|---|---|---|
| **Monde** | Ordre de grandeur des utilisateurs professionnels et stabilité de l'interface publique du tiers. | La pérennité de l'adaptateur. Un tiers mondial documente, versionne et prévient ; un tiers local change sans préavis. |
| **Continent africain** | Pénétration réelle chez les entreprises, et écart avec les usages du Nord. | La hiérarchie. C'est la maille qui fait remonter le mobile money et la messagerie très au-dessus de leur rang mondial. |
| **Madagascar et zone francophone visée** | Disponibilité effective du service, existence d'une interface accessible à un éditeur, et obligation légale. | Le caractère bloquant. Un connecteur peut être indispensable ici et sans objet ailleurs. |

Les sept paliers ci-dessous sont ordonnés par ce que la Phase 4 en retient, pas par leur poids économique mondial. Les chiffres cités datent de la période 2025–2026 et proviennent des sources listées en annexe 20.2 ; ils servent à établir des ordres de grandeur et des rangs, pas à être repris tels quels dans un document commercial.

### 3.2 Palier A — Bureautique et productivité

C'est le palier le plus peuplé au monde et le moins différenciant. Deux suites concentrent la quasi-totalité du marché des suites de productivité professionnelle. Mesurée en sièges payants d'entreprise, la suite de Microsoft dépasse les 450 millions et domine largement le segment des grandes organisations. Mesurée en nombre de domaines, la suite de Google passe devant, portée par les très petites et moyennes structures ; elle revendique plus de onze millions de clients payants et un usage total de l'ordre de trois milliards de personnes en incluant les comptes gratuits. Près des deux tiers des organisations utilisent les deux en parallèle, ce qui interdit de choisir l'une contre l'autre.

Sur la maille malgache, la lecture s'inverse encore : la très petite entreprise travaille massivement avec des comptes gratuits de messagerie et de stockage grand public, et l'usage professionnel se fait souvent sur un compte personnel. La conséquence de conception est nette : le connecteur doit fonctionner avec un compte individuel autorisé par délégation, pas seulement avec un annuaire d'entreprise administré.

| Tiers | Rang mondial (pro) | Poids sur la maille locale | Opérations attendues par les clients |
|---|---|---|---|
| **Suite Google (stockage, tableur, agenda, messagerie)** | 1 en nombre de domaines, 2 en sièges payants | Dominant chez la TPE et la PME ; usage courant en compte personnel | Déposer les archives et les états ; publier un tableau vivant ; poser les échéances d'exploitation dans un agenda ; envoyer un document depuis l'adresse du client. |
| **Suite Microsoft (stockage, tableur, agenda, messagerie)** | 1 en sièges payants, 2 en domaines | Présent chez l'entreprise structurée, la filiale de groupe et l'exportateur | Mêmes opérations. C'est la suite qu'exigera l'entreprise textile travaillant pour un donneur d'ordre étranger. |
| **Stockage objet compatible S3** | Standard de fait | Déjà en place depuis la Phase 1 pour la sauvegarde | Archivage à durée réglementaire, exports volumineux, dépôt de pièces probantes. Acquis, étendu. |

**Deux connecteurs de bureautique, pas quatre.** Il serait tentant de traiter séparément le stockage, le tableur, l'agenda et la messagerie de chaque suite : cela ferait huit adaptateurs. La conception retenue en compte deux, chacun exposant quatre opérations, parce que l'authentification, la gestion du jeton, le renouvellement et la traduction d'erreurs sont communs à toute la suite. C'est l'application directe de la deuxième décision structurante.

### 3.3 Palier B — Messagerie conversationnelle

Sur la maille africaine, la messagerie conversationnelle n'est pas un canal de plus : c'est **le** canal. Sa pénétration dépasse largement celle du courriel professionnel dans la plupart des marchés du continent, elle est le moyen par lequel un commercial reçoit une commande et par lequel un client réclame une facture. Le nombre d'entreprises raccordées à l'interface professionnelle de la messagerie dominante se compte en millions à l'échelle mondiale.

Ce palier est en grande partie livré : la Phase 2 a construit l'adaptateur de canal, la bibliothèque de modèles approuvés, le consentement et le journal de coût. La Phase 4 n'y ajoute qu'une mise à niveau, mais elle est structurante et elle invalide partiellement une hypothèse antérieure.

**Le modèle de facturation de la messagerie professionnelle a changé de maille.** La Phase 2 avait modélisé le coût par conversation, c'est-à-dire par fenêtre de vingt-quatre heures, en signalant que ces conditions évoluaient souvent (H8). Depuis le 1er juillet 2025, la facturation du fournisseur dominant s'établit au message de gabarit délivré, avec des catégories et des tarifs qui varient selon le pays du destinataire. Le compteur de coût livré en Phase 2 doit donc changer d'unité, et la migration des historiques doit être arbitrée : conserver deux unités coexistantes ou recalculer. C'est un travail court mais non nul, inscrit au bloc H et non au bloc de la messagerie, parce qu'il touche le compteur transverse.

### 3.4 Palier C — Argent et flux financiers

C'est le palier où l'écart entre la maille mondiale et la maille africaine est le plus violent, et c'est celui qui porte la valeur de la Phase 4. À l'échelle mondiale, le volume transitant par la monnaie électronique mobile a atteint l'ordre de deux mille milliards de dollars en 2025, soit un doublement en quatre ans. L'Afrique subsaharienne en concentre environ mille quatre cents milliards. Le continent héberge un peu plus de la moitié des comptes de monnaie électronique recensés dans le monde et près des trois quarts du nombre de transactions, soit de l'ordre de quatre-vingt-dix milliards d'opérations sur l'année, en croissance à deux chiffres. Le réseau d'agents dépasse trente millions de points dans le monde.

Sur la maille malgache, la situation est plus marquée encore. Le pays compte largement plus de quinze millions de comptes actifs, les flux de monnaie électronique représentent une fraction du produit intérieur brut de l'ordre de trente pour cent, et une majorité de la population adulte utilise l'un des trois services. En regard, la bancarisation classique reste faible — de l'ordre de moins de dix pour cent d'adultes titulaires d'un compte bancaire — et la carte bancaire active concerne une part de la population de l'ordre de trois pour cent. Le commerce en ligne, encore modeste, s'effectue à plus de deux tiers depuis un terminal mobile.

**La conclusion opérationnelle est sans ambiguïté** : pour un client de WideHalo à Madagascar, le connecteur d'encaissement qui compte n'est pas la passerelle de carte bancaire, c'est le portefeuille mobile. La carte reste utile pour la vente à l'étranger et pour la clientèle d'entreprise, elle n'est pas le cas nominal.

| Tiers | Position sur la maille locale | Voie de raccordement observée | Ce que le client attend |
|---|---|---|---|
| **Opérateur de monnaie électronique n° 1 (préfixes 034 / 038)** | Réseau d'agents le plus dense, y compris rural ; le plus utilisé du pays | Portail développeur public, environnement d'essai, jeton par identifiants d'application, interface de paiement marchand, procédure de bascule en production | Un lien ou un code de règlement envoyé au client, une confirmation qui revient seule, et une facture qui se solde sans ressaisie. |
| **Opérateur n° 2 (préfixes 032 / 037)** | Deuxième service, plus urbain ; grille de transfert modifiée en février 2026 | Contrat marchand ; conditions d'interface non documentées publiquement | Idem. En pratique, l'accès passera plus souvent par un agrégateur. |
| **Opérateur n° 3 (préfixe 033)** | Troisième service, couverture plus étroite | Contrat marchand ; accès indirect | Couverture de complétude, pour ne refuser aucun client. |
| **Agrégateurs de paiement locaux** | Plusieurs acteurs malgaches proposent une interface unique couvrant les trois opérateurs, parfois la carte | Interface unique documentée, notifications d'événement, versement périodique sur compte bancaire | Ne pas gérer trois contrats et trois formats. C'est l'argument décisif pour la PME. |
| **Banques de la place** | Indispensables pour l'entreprise formelle ; aucune interface publique | Fichier de relevé téléchargé par le client ; ordre de virement déposé | Un rapprochement qui se fait tout seul et une remise de virements qui ne se ressaisit pas. |
| **Passerelles de carte bancaire** | Marginales en volume, nécessaires à l'export et au commerce en ligne | Interface standard, contrat d'acquisition | Encaisser un client étranger sans passer par un intermédiaire informel. |

**Le choix qui structure tout le bloc financier**

Se raccorder directement à chaque opérateur donne le coût unitaire le plus bas et la maîtrise complète du comportement, au prix de trois enrôlements, trois formats, trois politiques de notification et trois sources de panne — multipliés par le nombre de tenants, puisque chaque client aura son propre contrat marchand. Passer par un agrégateur donne une interface unique et une mise en service courte, au prix d'une commission supplémentaire et d'une dépendance de plus. L'arbitrage complet figure en section 12.2 ; il est tranché en faveur d'une abstraction unique qui admet les deux voies, avec l'agrégateur comme mode par défaut et le raccordement direct comme option pour le tenant à fort volume.

### 3.5 Palier D — Conformité et flux réglementaires

C'est le palier qui n'admet aucun arbitrage, et il vient de changer de statut sur la maille malgache. Un décret publié le 2 juillet 2025 institue une obligation de facturation électronique pour l'ensemble des transactions entre entreprises et avec le secteur public, y compris celles exonérées de taxe sur la valeur ajoutée. Le dispositif repose sur une plateforme centrale de l'administration fiscale chargée de l'émission, de la réception et de l'archivage, adossée à un module de pré-remplissage des déclarations. L'entrée en vigueur est progressive et indexée sur la taille de l'entreprise : les grandes entreprises disposent d'un délai de l'ordre de six mois après la mise en service de la plateforme, les entreprises moyennes d'environ un an.

Trois conséquences suivent, et elles gouvernent le calendrier de la Phase 4.

- **La facture cesse d'être un document produit pour devenir un document soumis.** Un fichier lisible envoyé par courriel ne satisfait pas ce type d'obligation : il faut un document structuré, transmis, validé, revêtu d'un identifiant et d'un marquage de contrôle, puis archivé pour une durée réglementaire. Le module Sales de la Phase 1 n'est pas à réécrire, mais son étape terminale change de nature.
- **Le calendrier n'appartient pas à l'éditeur.** Le compte à rebours démarre à la mise en service d'une plateforme dont la date, le format d'échange et le mode d'habilitation ne sont pas publiés à la date de rédaction. C'est l'hypothèse H20, et c'est la plus lourde de la phase : elle justifie à elle seule le découpage en deux vagues.
- **L'abstraction construite ici est le billet d'entrée régional.** Plusieurs pays de la zone francophone visée exploitent déjà des dispositifs comparables — facture normalisée électronique validée avant remise au client en Côte d'Ivoire, dispositif de certification en place depuis 2020 au Bénin, dispositifs voisins au Niger, au Mali et au Burkina Faso, obligation posée en loi de finances au Sénégal. Les mécanismes diffèrent dans le détail et se ressemblent dans la structure : préparer, soumettre, obtenir un verdict, recevoir un identifiant et un marquage vérifiable, archiver. Concevoir cette structure comme un moteur paramétré par pays, plutôt que comme un connecteur malgache, coûte environ deux sprints de plus et vaut la localisation OHADA future.

| Flux réglementaire | État sur la maille locale | Traitement en Phase 4 |
|---|---|---|
| **Facturation électronique à validation préalable** | Obligation instituée, plateforme centrale annoncée, calendrier indexé sur sa mise en service | Livré, sous forme de moteur de dispositif à contrôle continu paramétré par pays, avec un mode d'attente tant que le raccordement réel n'est pas ouvert (H20, H21). |
| **Pré-remplissage et télédéclaration fiscale** | Annoncé comme module de la plateforme centrale | Partiellement livré : les états sont produits et exportés comme en Phase 3 ; le dépôt automatique reste hors périmètre tant que l'interface n'est pas connue. |
| **Déclarations sociales** | Documentaire, reconduit de la Phase 3 (H18) | Non livré. Les états restent produits et déposés hors de l'outil. |
| **Reçu normalisé de caisse** | Existe dans certains dispositifs régionaux, adossé à un terminal dédié | Anticipé, non livré. Le POS produit déjà un ticket numéroté et inviolable ; le point d'accroche est prévu, comme le mouvement indicatif l'était en Phase 1. |

### 3.6 Palier E — Commerce et canaux de vente

À l'échelle mondiale, le socle de boutique en ligne le plus répandu en nombre de sites reste une extension de plateforme de publication, devant les solutions hébergées. Sur la maille malgache, le commerce en ligne progresse mais reste minoritaire, et la vente à distance passe souvent par la conversation et le portefeuille mobile plutôt que par un panier. Le palier est donc réel mais secondaire, et il est traité par un connecteur générique plutôt que par un adaptateur par plateforme : publication d'un catalogue et de disponibilités, ingestion des commandes, retour d'un statut d'expédition, sur une base de fichiers et d'appels normalisés que n'importe quelle boutique sait consommer.

### 3.7 Palier F — Automatisation et orchestration

Ce palier ne se connecte pas : il se laisse connecter. Trois plateformes dominent la conversation. La plus répandue revendique de l'ordre de trois millions d'utilisateurs, plus de cent mille clients payants et un catalogue de plusieurs milliers d'intégrations ; la deuxième occupe un segment intermédiaire ; la troisième, ouverte et auto-hébergeable, a connu une croissance rapide et compte quelques centaines de milliers d'utilisateurs visibles, avec un usage réel supérieur du fait de son mode d'installation. L'automatisation assistée est désormais utilisée par une large majorité d'organisations dans au moins une fonction, et son adoption dans les petites structures a presque doublé en deux ans. Les analystes constatent par ailleurs la fusion progressive des catégories d'intégration, d'automatisation robotisée et de flux de travail.

**La décision qui en découle est de ne rien intégrer de tout cela et de tout rendre intégrable.** Construire quarante adaptateurs pour rattraper un catalogue de plusieurs milliers est perdu d'avance pour un développeur seul. Exposer une interface publique propre, versionnée et documentée, plus des notifications sortantes signées, place WideHalo à l'intérieur de ces catalogues sans que l'éditeur n'entretienne un seul de leurs connecteurs. La plateforme auto-hébergeable est recommandée dans la documentation d'exploitation, parce qu'elle s'installe dans la même pile de conteneurs que le reste et qu'elle ne fait pas sortir les données du serveur du client — mais elle n'est ni embarquée, ni supportée, ni facturée.

### 3.8 Palier G — Terrain, matériel et flux locaux

Reconduit sans changement depuis les Phases 1 et 3 : lecteur de codes-barres en émulation clavier, imprimante d'étiquettes en flux d'impression standard, aucun pilote ni composant à installer sur le poste. La Phase 4 ajoute un seul élément, et il est logiciel : le dépôt et la reprise de fichiers sur un partage local du client, pour les entreprises dont la contrainte n'est pas le nuage mais la coupure — un export nocturne qui atterrit sur un disque de l'entreprise reste lisible quand la liaison internet est tombée.

### 3.9 Matrice de priorisation

La matrice ci-dessous applique l'ordre annoncé en décision structurante n° 3. Le score n'est pas une moyenne : une obligation réglementaire l'emporte sur n'importe quelle combinaison des autres critères, et un tiers sans voie de raccordement accessible est reporté quelle que soit sa désirabilité.

| Connecteur | Caractère | Portée locale | Accès technique | Charge d'entretien | Rang | Décision Phase 4 |
|---|---|---|---|---|---|---|
| **Facturation électronique à validation préalable** | Obligatoire | Toutes les entreprises formelles | Inconnu à ce jour (H20, H21) | Élevée — texte mouvant | 1 | Livré, vague 4A, avec mode d'attente |
| **Encaissement par monnaie électronique mobile** | Décisif | Majorité des adultes | Portail public ou agrégateur | Moyenne | 2 | Livré, vague 4B |
| **API publique et notifications sortantes** | Structurant | Intégrateurs, clients avancés | Maîtrisé — c'est nous | Faible | 3 | Livré, vague 4A |
| **Relevés bancaires et ordres de virement** | Fort | Toute entreprise bancarisée | Fichier, pas d'interface (H25) | Faible | 4 | Livré, vague 4B |
| **Messagerie conversationnelle** | Fort | Canal dominant | Acquis Phase 2, à mettre à niveau | Moyenne — règles du fournisseur | 5 | Mise à niveau, vague 4B |
| **Bureautique et stockage (deux suites)** | Confort élevé | Quasi universelle | Standard, stable, documenté | Faible | 6 | Livré, vague 4B |
| **Commerce en ligne, générique** | Confort | Minoritaire mais croissante | Fichiers et appels normalisés | Faible | 7 | Livré en générique, vague 4B |
| **Passerelle de carte bancaire** | Complément | Export et clientèle d'entreprise | Standard | Faible | 8 | Prévu dans l'abstraction, activé à la demande |
| **Partage de fichiers local** | Complément | Clients à liaison instable | Trivial | Très faible | 9 | Livré, vague 4B |
| **Plateformes d'automatisation** | Écosystème | Faible mais qualifiée | Sans objet — c'est elles qui nous appellent | Nulle | — | Non livré. Documenté et rendu possible par l'API. |
| **Télédéclaration sociale et fiscale** | Souhaitable | Toutes | Non ouvert (H18) | Élevée | — | Non livré. Reconduit en documentaire. |
| **Système douanier** | Souhaitable | Importateurs | Non vérifié (H15) | Élevée | — | Non livré. Reconduit en documentaire. |

**Neuf familles livrées, douze adaptateurs au plafond, aucun développement spécifique client.** La matrice donne neuf familles retenues. Le plafond d'adaptateurs est fixé à douze pour laisser trois places de manœuvre — un second agrégateur de paiement, un second pays de conformité, une passerelle de carte. Toute demande au-delà de ce plafond se traite par l'API publique, y compris si elle vient d'un client important. C'est la seule règle qui empêche le catalogue de connecteurs de devenir, en dix-huit mois, la partie du produit qui consomme tout le temps disponible.

## 4. Opérations attendues sur les liaisons

*Huit verbes, quatre déclencheurs, sept axes de réglage — et rien d'autre*

La section 3 dit à quoi se brancher. Celle-ci dit ce que « se brancher » veut dire, et c'est la contrainte la plus utile du document : tant que l'inventaire des opérations reste fermé, ajouter un tiers reste bon marché. Le jour où un connecteur exige un neuvième verbe, c'est le signal qu'il ne relève pas de ce socle et qu'il doit être refusé ou traité comme un module à part entière, avec son chiffrage propre.

### 4.1 Les huit opérations canoniques

| Réf. | Opération | Sens | Réponse | Exemple de la Phase 4 | Ce qu'elle impose au socle |
|---|---|---|---|---|---|
| **OP1** | Pousser un document | Sortant | Accusé technique | Envoyer une facture ou un bon de commande à un tiers, au format lisible et structuré | Empreinte du document envoyé, pour prouver ce qui est parti. |
| **OP2** | Publier un jeu de données | Sortant | Accusé technique | Alimenter une feuille de calcul de suivi, publier un catalogue vers une boutique | Fenêtre de portée, différentiel depuis le dernier envoi, sinon le volume explose. |
| **OP3** | Déposer un fichier | Sortant | Emplacement | Archiver une liasse, déposer un export nocturne sur un espace de stockage ou un partage local | Convention de nommage et d'arborescence paramétrable, sinon le client ne retrouve rien. |
| **OP4** | Soumettre pour validation | Sortant, avec verdict | Accepté, rejeté ou en attente | Transmettre une facture à une plateforme fiscale et recevoir son identifiant et son marquage | Machine à états à trois issues, motif de rejet exploitable, non-répudiation du verdict. |
| **OP5** | Initier un mouvement d'argent | Sortant, confirmation différée | Asynchrone | Créer une intention de règlement mobile, produire un ordre de virement | Idempotence stricte, corrélation, tolérance à la confirmation qui n'arrive jamais. |
| **OP6** | Ingérer un lot | Entrant | Compte rendu | Importer un relevé bancaire, un catalogue fournisseur, un fichier de commandes | Détection de doublon, ligne en anomalie isolée sans bloquer le lot, rapport de chargement. |
| **OP7** | Recevoir un événement | Entrant | Immédiate | Notification de paiement encaissé, verdict fiscal asynchrone, commande créée en boutique | Authentification de l'appelant, protection contre le rejeu, réponse rapide puis traitement différé. |
| **OP8** | Interroger un référentiel | Sortant, lecture | Synchrone | Vérifier un identifiant fiscal, relever un cours de change, contrôler un compte marchand | Mise en cache avec durée de validité, dégradation en valeur saisie si le tiers ne répond pas. |

Les cinq premières opérations écrivent vers l'extérieur, les trois dernières lisent ou reçoivent. Cette symétrie est le fondement du modèle de données de la section 13 : une seule table d'échange porte les huit, avec un attribut de sens et un attribut d'opération. Un connecteur se décrit alors par le sous-ensemble d'opérations qu'il implémente, et rien de plus.

### 4.2 Les quatre modes de déclenchement

| Mode | Déclenché par | Usage typique et contrainte propre |
|---|---|---|
| **Manuel** | Une action explicite de l'utilisateur sur une pièce ou un écran | Le mode de première mise en service et de rattrapage. Contrainte : l'utilisateur doit voir l'état réel de son action, jamais un faux succès. C'est la règle posée en Phase 1 pour le courriel, généralisée. |
| **Planifié** | Un calendrier avec fenêtre, fréquence et fuseau | Exports nocturnes, publication de catalogue, ingestion de relevé. Contrainte : la fenêtre doit être arbitrable par tenant, pour ne pas entrer en concurrence avec le rafraîchissement analytique et le calcul de besoins de la Phase 3. |
| **Événementiel** | Une transition du moteur de workflow interne | « Facture validée » déclenche la soumission ; « expédition confirmée » déclenche le retour de statut. Contrainte : le déclenchement ne doit jamais bloquer la transition métier. L'échange est mis en file, la transition aboutit. |
| **Réactif** | Un appel entrant du tiers, authentifié | Notification de paiement, verdict différé, commande créée. Contrainte : réponse en quelques centaines de millisecondes puis traitement asynchrone, sinon le tiers considère l'appel en échec et le répète. |

### 4.3 Les sept axes de personnalisation

« Personnalisable » est un mot dangereux dans un cahier des charges : appliqué sans limite, il produit un langage de programmation déguisé. Sept axes sont ouverts au paramétrage par le client, et ils sont limitatifs. Tout le reste relève de l'adaptateur, donc de l'éditeur.

| Axe | Ce que le client règle | Bornes |
|---|---|---|
| **A1** | Portée — quels objets partent | Filtres sur des champs déclarés du modèle, jamais une expression libre. Un filtre non déclaré est refusé à l'enregistrement. |
| **A2** | Correspondance de champs | Association un pour un entre champ source et champ cible, avec un jeu fermé de transformations : format de date, séparateur décimal, casse, concaténation, valeur constante, table de correspondance de valeurs. |
| **A3** | Gabarit de rendu | Modèles de document et de message dérivés du moteur de la Phase 1, avec variables déclarées. Approbation préalable là où le tiers l'impose. |
| **A4** | Calendrier | Fréquence, fenêtre horaire, fuseau, jours d'exclusion adossés au calendrier malgache paramétré en Phase 2. |
| **A5** | Politique d'échec | Nombre de tentatives, espacement, seuil de disjoncteur, destinataire de l'alerte, comportement au-delà : mise en attente ou abandon tracé. |
| **A6** | Plafond de coût | Montant ou volume par période et par catégorie, action au plafond, destinataire de l'avertissement à l'approche du seuil. |
| **A7** | Consentement de sortie | Activation explicite du connecteur, avec affichage en clair des catégories de données qui sortiront et journalisation de la décision. |

### 4.4 Ce que « automatisable » n'autorise pas

Trois interdits, tous formulés pour être vérifiés par un test plutôt que respectés par discipline.

- **Aucune automatisation ne crée ou ne modifie une pièce comptable.** Un flux entrant propose, un humain ou une règle métier déjà éprouvée dispose. Un relevé bancaire ingéré produit des propositions de lettrage, pas des écritures. Une commande reçue d'une boutique produit un document au statut initial, pas une facture validée.
- **Aucune automatisation ne franchit une frontière de tenant.** Le contrôle est le même que celui posé en Phase 1 pour le copilote et vérifié par un test d'isolation à deux tenants, étendu aux jetons d'API et aux appels entrants.
- **Aucune automatisation ne s'exécute sans laisser une ligne dans le registre.** Y compris lorsqu'elle échoue, y compris lorsqu'elle est annulée par un plafond, y compris lorsqu'elle est déclenchée par un tiers. Un échange sans trace est un défaut bloquant, pas une optimisation.

## 5. Utilisateurs cibles et cas d'usage

*Un utilisateur nouveau, qui n'est pas dans l'entreprise*

### 5.1 Trois profils nouveaux

Les Phases 1 à 3 servaient des utilisateurs internes : des commerciaux assis, des dirigeants qui consultent, des opérateurs debout. La Phase 4 en ajoute trois, et le premier n'est pas humain.

| Profil | Ce qu'il fait | Ce que le produit lui doit |
|---|---|---|
| **Le système tiers** | Appelle l'API publique ou reçoit une notification. Ne lit aucune documentation contextuelle, ne devine rien, ne pardonne rien. | Une surface stable et versionnée, des codes d'erreur explicites, une idempotence garantie, et une documentation qui suffit sans support. |
| **L'administrateur de flux** | Dans les PME visées, c'est le comptable ou le dirigeant, pas un informaticien. Il active un connecteur, règle un calendrier, constate un échec. | Un vocabulaire d'échec compréhensible sans culture technique, une action de reprise évidente, et jamais une exigence de savoir ce qu'est un jeton. |
| **L'intégrateur externe** | Prestataire mandaté par le client pour brancher WideHalo sur un outil non couvert. | Un environnement d'essai, des clés à portée restreinte, un journal d'appel consultable, et l'assurance de ne pas pouvoir casser la production. |

### 5.2 Parcours de référence de la Phase 4

Le parcours ci-dessous est celui sur lequel la recette fonctionnelle est écrite. Il enchaîne les quatre familles les plus structurantes sur une seule pièce, ce qui est précisément la difficulté : chaque étape doit se rattacher à la même facture, dans le même registre.

****Parcours de référence — une facture, quatre familles, un registre****

```
   VENTE                CONFORMITÉ              ARGENT              COMPTABILITÉ
 ┌──────────┐         ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
 │ Facture  │ valid.  │ Soumission   │ verd.│ Intention de │ notif│ Encaissement │
 │ (Ph. 1)  │────────>│ plateforme   │─────>│ règlement    │─────>│ + lettrage   │
 │          │ déclen- │ fiscale (OP4)│ ident│ mobile (OP5) │ (OP7)│ automatique  │
 └────┬─────┘ cheur   └──────┬───────┘ + mrq└──────┬───────┘      └──────┬───────┘
      │                      │                     │                     │
      │                      ▼                     ▼                     ▼
      │        ┌────────────────────────────────────────────────────────────────┐
      └───────>│  REGISTRE D'ÉCHANGE — une ligne par tentative, corrélée         │
               │  id · tenant · liaison · sens · opération · pièce · empreinte   │
               │  horodatage · statut · tentative · coût · clé de corrélation    │
               └────────────────────────────────┬───────────────────────────────┘
                                                ▼
                    ┌───────────────────────────┬────────────────────────────┐
                    │ RESTITUTION               │ RELEVÉ BANCAIRE            │
                    │ dépôt de la liasse (OP3)  │ ingéré (OP6) et rapproché  │
                    │                           │ du versement groupé        │
                    └───────────────────────────┴────────────────────────────┘
```

Deux points de ce parcours méritent d'être soulignés, parce qu'ils sont les pièges les plus coûteux de la phase. Le premier est que **la validation fiscale et le règlement sont indépendants** : une facture peut être payée avant d'être validée, ou rejetée après avoir été payée. Le modèle ne doit donc pas les séquencer. Le second est que **le versement de l'agrégateur sur le compte bancaire arrive en différé et agrégé** : le relevé bancaire ne contient pas les encaissements individuels mais leur somme, diminuée d'une commission. Le rapprochement se fait donc à deux niveaux — encaissement contre facture, puis versement groupé contre lot d'encaissements — et c'est la partie du bloc D que l'on sous-estime systématiquement.

## 6. Contraintes du projet

*Une phase dont le calendrier dépend de tiers, pour la première fois*

| Contrainte | Énoncé | Conséquence sur la conception |
|---|---|---|
| **Équipe** | Un développeur, avec trois phases en production à supporter. Capacité retenue : 3,5 jours effectifs par semaine. | Neuf blocs plutôt que douze modules, plafond d'adaptateurs, refus assumé du développement spécifique. |
| **Calendrier externe** | La date d'ouverture du raccordement fiscal n'est pas connue et ne dépend pas de l'éditeur. | La vague 4A livre le moteur et un mode d'attente vérifiable, sans attendre la publication des spécifications. |
| **Enrôlements administratifs** | Habilitations, contrats marchands et déclarations d'application ont des délais non maîtrisés. | Les démarches sont engagées quatre sprints avant le bloc qui les consomme, et inscrites en suites immédiates. |
| **Coût variable** | Plusieurs tiers facturent à l'usage, avec des grilles qui changent. | Aucun tarif dans le code ; compteur, imputation et plafond obligatoires avant l'activation de tout connecteur payant. |
| **Infrastructure** | Enveloppe serveur inchangée, deux files de worker existantes. | Une troisième file dédiée aux échanges, isolée, pour qu'un tiers lent ne retarde ni l'interactif ni le nocturne. |
| **Réseau** | Liaison internet du client instable ; celle du serveur ne l'est pas moins. | File de sortie persistante, réessai avec espacement croissant, disjoncteur, et dépôt local en repli. |
| **Budget d'architecture** | Les plafonds de modèles, d'endpoints et d'écrans sont vérifiés en intégration continue. | Rehaussés en section 11.1, jamais contournés. Un budget dépassé fait échouer la construction. |

### 6.1 Hypothèses ouvertes à lever

Onze hypothèses conditionnent la Phase 4. Elles reprennent la numérotation continue des phases précédentes. Sept d'entre elles portent sur des tiers, ce qui est la nature même de cette phase ; le tableau indique pour chacune l'échéance de levée et l'effet si elle se révèle fausse.

| Réf. | Hypothèse | Levée au plus tard | Effet si fausse |
|---|---|---|---|
| **H20** | La plateforme fiscale centrale ouvre son raccordement, avec un format et un mode d'échange publiés, dans un délai compatible avec la vague 4A. | Sprint 10 | Le moteur reste livré en mode d'attente : le document normalisé est produit et archivé, la soumission est mise en file. Le produit n'est pas conforme mais il est prêt. C'est le seul scénario acceptable. |
| **H21** | L'habilitation d'un éditeur ou d'un contribuable au dispositif est obtenable dans un délai et à un coût connus. | Sprint 10 | Le raccordement passe par un tiers de confiance, avec surcoût par document. Arbitrage en 12.3. |
| **H22** | L'interface de paiement marchand de l'opérateur principal est utilisable par un éditeur agissant pour le compte de plusieurs marchands distincts. | Sprint 15 | Chaque tenant fait sa propre déclaration d'application, et l'onboarding devient une prestation. Le développement ne change pas, le modèle commercial si. |
| **H23** | Les deux autres opérateurs de monnaie électronique proposent une voie de raccordement documentée. | Sprint 15 | Ils ne sont atteints que par agrégateur. Sans conséquence si H24 tient. |
| **H24** | Un agrégateur local accepte un contrat permettant à un éditeur d'exposer le service à ses tenants. | Sprint 15 | Retour au raccordement direct par tenant, avec trois enrôlements. Coût de mise en service par client fortement accru. |
| **H25** | Les banques de la place fournissent un relevé téléchargeable dans un format stable et analysable. | Sprint 22 | Le bloc E se réduit à un import de tableur avec correspondance de colonnes paramétrable — dégradation acceptable, déjà prévue en conception. |
| **H26** | Le passage de la messagerie professionnelle à une facturation au message est correctement modélisable dans le compteur existant sans reprise de l'historique. | Sprint 3 | Deux unités de coût coexistent, avec une date de bascule. Un sprint supplémentaire au bloc H. |
| **H27** | Le cadre malgache de protection des données personnelles n'impose pas de formalité préalable spécifique aux transferts vers un prestataire situé hors du territoire, au-delà de l'information et du consentement. | Sprint 6 | Le consentement de sortie devient un formalisme opposable avec pièce à produire, et certains connecteurs deviennent conditionnels. Aucun développement supplémentaire lourd : le mécanisme A7 le porte déjà. |
| **H28** | Le rythme de rupture des interfaces tierces reste absorbable par une personne, à raison de deux à quatre ruptures par an et par connecteur actif. | Mesure continue | Le plafond de douze descend à huit, et les connecteurs de confort sont retirés du catalogue. C'est la mesure la plus importante à instrumenter dès le bloc A. |
| **H29** | Les clients acceptent un abonnement distinct pour le connecteur réglementaire. | Sprint 8 | Le connecteur passe au socle inclus et son coût est reporté sur le prix de base. Décision commerciale, sans effet technique. |
| **H30** | Une plateforme d'automatisation auto-hébergée tient dans l'enveloppe serveur existante aux côtés du modèle de langage local. | Sprint 9 | Elle est recommandée sur une instance séparée à la charge du client. Sans effet sur le périmètre livré. |

**H20 est d'une nature différente des dix autres.** Les hypothèses techniques se lèvent en lisant une documentation ou en faisant un essai. Celle-ci se lève par la publication d'un texte d'application et l'ouverture d'un service public, événements sur lesquels ni l'éditeur ni le client n'ont de prise, et dont l'expérience des dispositifs comparables dans la région montre qu'ils glissent souvent de plusieurs trimestres. La conception doit donc traiter le retard comme le cas nominal et non comme un incident : le moteur de conformité est réputé complet lorsqu'il produit, archive et met en file un document normalisé sans qu'aucune plateforme ne soit joignable, et lorsqu'il rejoue cette file sans perte le jour de l'ouverture.

## 7. Architecture applicative

*Une brique nouvelle à l'intérieur du monolithe, et une seule*

La Phase 4 n'introduit aucun composant d'infrastructure nouveau et n'ouvre aucun service séparé. Elle ajoute une brique à l'intérieur du monolithe modulaire existant : **le hub de flux**, qui porte le registre d'échange, la file de sortie, la surface entrante et le catalogue d'adaptateurs. Le gateway IA reste le seul service distinct, tel qu'il a été livré en Phase 1. C'est le bénéfice cumulé des abstractions des trois phases précédentes : ce qui aurait été une refonte de la couche d'intégration devient un ajout.

### 7.1 Chaîne de flux — Phase 4

****Chaîne de flux — Phase 4****

```
┌──────────────────────────────────────────────────────────────────────┐
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ SOURCES MÉTIER (Phases 1 à 3, inchangées)                        │ │
│ │   CRM · Sales · Accounting · POS · Stock · Achats · Production · │ │
│ │   Qualité · Paie · BI · Forecast · Strategy                      │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│         │ déclencheur              ▲ proposition                     │
│         ▼ de workflow              │ jamais écriture                 │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ HUB DE FLUX — brique nouvelle de la Phase 4                      │ │
│ │   LIAISONS         REGISTRE D'ÉCHANGE        FILE DE SORTIE      │ │
│ │   connecteur +     une ligne par tentative   persistante,        │ │
│ │   opération +      empreinte · corrélation   réessai espacé,     │ │
│ │   objet + sens     statut · coût · verdict   disjoncteur         │ │
│ │                                                                  │ │
│ │   CORRESPONDANCES  PLANIFICATION             SURFACE ENTRANTE    │ │
│ │   champ à champ,   calendrier, fenêtre,      webhooks signés,    │ │
│ │   transformations  fuseau, exclusions        API publique,       │ │
│ │   déclarées        (calendrier Ph. 2)        clés et portées     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│         │                          ▲                                 │
│         ▼                          │                                 │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ ADAPTATEURS — plafond 12. Authentification, protocole, erreurs.  │ │
│ │  conformité · monnaie mobile · agrégateur · banque ·             │ │
│ │  suite Google · suite Microsoft · stockage objet ·               │ │
│ │  partage local · commerce · messagerie (Ph. 2) ·                 │ │
│ │  courriel (Ph. 1) · réserve ×2                                   │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
      │                     │                          │
      ▼                     ▼                          ▼
 CONSOLE DE FLUX      ENTREPÔT (Ph. 2)           COPILOTE (Ph. 1)
 états · coûts ·      faits d'échange :          lecture seule sur
 plafonds · rejeu     volume · latence ·         l'état des flux.
 consentements        succès · coût              Aucun déclenchement.
```

### 7.2 Couche présentation

Neuf composants nouveaux seulement, détaillés en section 10.2, tous liés à la représentation d'un état incertain — un envoi en cours, un verdict en attente, un paiement dont on ne sait pas encore s'il arrivera. Les écrans de la console de flux sont majoritairement construits par le moteur de vues et le data grid livrés en Phase 1 : un échange est une ligne, une liaison est une fiche, un incident est un document avec un chatter. Le reste des écrans de la phase est constitué de fragments greffés sur les écrans existants — un bandeau d'état fiscal sur la facture, un bouton de règlement sur le ticket, un indicateur de synchronisation sur le catalogue.

### 7.3 Couche logique métier

Le hub de flux est une couche de services applicatifs comme les autres, soumise à la même règle qu'en Phase 1 : aucune logique dans les gabarits, aucune dans le code client, aucune dupliquée dans des déclencheurs de base. Trois services le composent — **le répartiteur**, qui traduit un déclencheur en échange ; **l'exécuteur**, qui appelle l'adaptateur et écrit le résultat ; **le réconciliateur**, qui rapproche un événement entrant d'une pièce métier. La règle qui les gouverne est que l'exécuteur ne connaît aucun tiers : il connaît des opérations et des adaptateurs, ce qui rend le socle testable sans réseau.

Le moteur de workflow déclaratif de la Phase 1 est étendu d'un seul effet de bord : « produire un échange ». Cet effet est asynchrone par construction et ne peut pas faire échouer la transition qui l'a déclenché — décision qui interdit, par exemple, qu'une plateforme fiscale indisponible empêche de valider une facture.

### 7.4 Couche données

PostgreSQL, base unique, isolation par discriminant et sécurité au niveau des lignes : inchangé depuis la Phase 1 et non rediscuté. La Phase 4 ajoute deux exigences propres. La première est le **partitionnement du registre d'échange par mois** dès la conception, pour la même raison qu'en Phase 3 pour le mouvement de stock : la table la plus volumineuse du produit ne se partitionne pas après coup. La seconde est la **séparation physique de la charge utile et de son enregistrement** : le contenu échangé vit dans une table distincte, chiffrée, avec sa propre durée de rétention, afin qu'une purge de contenu ne détruise pas la preuve qu'un échange a eu lieu.

### 7.5 Couche intégration

C'est la couche que cette phase construit, et la section 13 lui est entièrement consacrée. Deux principes la gouvernent, tous deux hérités et durcis. Premièrement, **aucun composant à installer sur le poste** : reconduit des Phases 1 et 3, y compris pour le partage local, atteint par dépôt de fichier et non par agent. Deuxièmement, **aucun accès direct à la base par un tiers** : l'API publique traverse la même couche de services que l'interface utilisateur, avec les mêmes contrôles de rôle, exactement comme le gateway IA le fait depuis la Phase 1.

Le gateway IA gagne des outils de lecture sur l'état des flux — combien d'échanges en attente, quel connecteur est en incident, quel plafond est proche. Il n'en gagne aucun de déclenchement : le copilote ne peut ni envoyer, ni rejouer, ni activer un connecteur. C'est une exclusion de principe, du même ordre que celle posée sur la paie en Phase 3, et elle est vérifiée en intégration continue.

### 7.6 Infrastructure

Enveloppe inchangée. Une troisième file de worker est ajoutée, dédiée aux échanges, isolée des deux existantes. La raison est simple et vaut d'être écrite : un tiers lent est la première cause de saturation d'une file partagée, et si la file d'échange saturait la file courte, une plateforme fiscale en difficulté rendrait l'ERP inutilisable. Trois ajouts d'exploitation : une supervision de la profondeur de la file de sortie, une alerte sur l'ouverture d'un disjoncteur, et un contrôle quotidien de cohérence entre les échanges au statut « accepté » et les pièces métier correspondantes.

### 7.7 Couche transverse

Sécurité (section 8) et gouvernance des données (section 9) traversent toutes les couches. La Phase 4 y ajoute un changement d'échelle plutôt qu'un changement de nature : le journal d'audit, devenu pièce opposable en Phase 3, doit désormais soutenir une opposabilité externe. Prouver à un salarié qu'un bulletin est celui qui lui a été remis est une chose ; prouver à une administration qu'une facture a été soumise à telle heure, ou à un client qu'un paiement a été notifié et rapproché, en est une autre, parce que le contradicteur n'est plus dans l'entreprise.

## 8. Sécurité

*La surface d'attaque triple : des secrets, des portes entrantes, des preuves*

Les Phases 1 à 3 protégeaient une application dont toutes les entrées passaient par une session authentifiée. La Phase 4 ouvre trois surfaces nouvelles, chacune avec sa réponse propre : des secrets de tiers stockés durablement, des points d'entrée appelables sans session humaine, et des enregistrements dont la valeur tient à leur opposabilité face à un tiers. Les priorités des phases précédentes restent valables et ne sont pas rediscutées : isolation entre clients, traçabilité des écritures, cloisonnement de la paie, confinement du copilote.

### 8.1 Secrets et identifiants de tiers

| Exigence | Mise en œuvre et vérification |
|---|---|
| **Chiffrement au repos** | Tout secret d'accès à un tiers est chiffré en base avec une clé maîtresse hors base, portée par l'environnement d'exécution. Aucun secret en clair, aucun secret dans une variable de configuration versionnée, aucun secret dans un export. |
| **Non-lisibilité après saisie** | Un secret saisi n'est plus jamais affiché, même à un administrateur. L'écran montre une empreinte partielle et une date de dernière rotation. Le remplacer est possible, le relire ne l'est pas. |
| **Portée minimale** | Chaque identifiant est demandé avec la portée strictement nécessaire à l'opération déclarée par l'adaptateur. La portée demandée est affichée au client au moment du consentement de sortie (A7). |
| **Rotation et expiration** | Date d'expiration suivie, alerte avant échéance, renouvellement automatique là où le protocole le permet. Un jeton expiré ouvre un incident, il ne produit pas une série d'échecs silencieux. |
| **Cloisonnement par tenant** | Un secret appartient à un tenant. La sécurité au niveau des lignes s'applique à la table de secrets comme aux autres, et un test d'isolation à deux tenants le vérifie. |
| **Absence dans les traces** | Un filtre de rédaction s'applique aux journaux, aux charges utiles archivées et aux messages d'erreur remontés à l'utilisateur. Un test échoue si un motif ressemblant à un secret apparaît dans une trace. |

### 8.2 Surface entrante : webhooks et API publique

Deux portes nouvelles, avec des menaces différentes. Le webhook est appelé par un tiers connu mais sur une adresse publique ; l'API publique est appelée par un client du tenant, avec une clé qu'il peut perdre.

- **Authentification de l'appelant.** Signature calculée sur le corps du message avec un secret partagé, vérifiée avant tout traitement. Un appel non signé ou mal signé est rejeté sans être traité et sans révéler pourquoi.
- **Protection contre le rejeu.** Horodatage dans une fenêtre courte, identifiant d'événement conservé, second passage ignoré et journalisé comme doublon. Sans cela, un même paiement peut être enregistré deux fois — c'est le défaut le plus coûteux de cette famille.
- **Découplage réception et traitement.** Le point d'entrée accuse réception puis met en file. Un traitement long dans la réponse conduit le tiers à réémettre, ce qui amplifie l'incident au lieu de l'absorber.
- **Portées et quotas par clé.** Une clé d'API porte une liste d'opérations autorisées, un débit maximal et une date d'expiration. La révocation est immédiate et rétroactive sur les appels en cours.
- **Aucune élévation par l'API.** Un jeton client ne peut obtenir aucune donnée qu'un utilisateur du même rôle ne pourrait consulter dans l'interface. Le contrôle est celui de la Phase 1 pour le copilote, réutilisé sans modification.
- **Adresses de webhook non devinables** et propres à chaque tenant et connecteur, révocables individuellement sans affecter les autres liaisons.

### 8.3 Non-répudiation des échanges

Un échange dont on ne peut pas prouver le contenu n'a aucune valeur devant un tiers. Trois exigences, toutes vérifiables.

- **Empreinte du contenu émis et reçu.** Calculée à l'émission et à la réception, stockée dans le registre indépendamment de la charge utile. Elle survit à la purge du contenu et permet de démontrer qu'un document produit aujourd'hui est bien celui qui est parti à l'époque.
- **Horodatage fiable et immuable.** Enregistré à la source, jamais recalculé, jamais modifiable par une reprise de données. Le journal d'audit hérite ici des exigences d'intégrité posées en section 6.2 de la Phase 3.
- **Conservation du verdict tel que reçu.** Le message de réponse d'un tiers — acceptation, identifiant attribué, marquage, motif de rejet — est conservé dans sa forme d'origine, en plus de son interprétation par le produit. Interpréter est utile ; ne conserver que l'interprétation rend la preuve inutilisable.

### 8.4 Confinement du copilote, étendu aux flux

Le copilote gagne trois outils de lecture — état des connecteurs, échanges en anomalie, consommation face aux plafonds — et aucun outil d'action. Il ne peut ni déclencher un échange, ni rejouer un échec, ni activer ou désactiver une liaison, ni lire une charge utile, ni lire un secret. Deux critères d'intégration continue le vérifient, sur le modèle des critères IA-1 à IA-5 de la Phase 1. La raison n'est pas la méfiance envers le modèle mais la nature de l'action : un envoi est irréversible, et une instruction hostile glissée dans un libellé de facture ne doit pas pouvoir déclencher un mouvement d'argent.

## 9. Gouvernance des données et souveraineté

*Le moment où les données du client quittent le serveur du client*

Jusqu'ici, la promesse de WideHalo était simple à tenir : les données restent chez le client, auto-hébergées, et le seul flux sortant optionnel était le repli du copilote vers un modèle distant. La Phase 4 rend cette promesse plus difficile et plus importante à la fois. Un connecteur, par définition, fait sortir de la donnée. La réponse n'est pas d'y renoncer mais de rendre chaque sortie visible, choisie, bornée et réversible.

### 9.1 Le consentement de sortie

Aucun connecteur n'est actif par défaut. Son activation est une décision explicite, par tenant, prise sur un écran qui affiche en clair, avant validation, quatre informations : quelles catégories de données sortiront, vers quel tiers, dans quel pays si l'information est disponible, et pour quelle durée de conservation chez ce tiers si elle est connue. La décision est journalisée avec son auteur et sa date, et elle est révocable. Une révocation coupe le connecteur immédiatement, laisse les échanges déjà réalisés dans le registre, et déclenche la purge de la charge utile encore conservée localement si le client le demande.

Ce mécanisme n'est pas une case à cocher juridique. Il est le seul moyen, pour un éditeur qui vend l'auto-hébergement comme argument, de rester cohérent en ouvrant neuf connecteurs.

### 9.2 Classification des données sortantes

| Catégorie | Sensibilité | Connecteurs concernés | Règle |
|---|---|---|---|
| **Pièce commerciale complète (facture, commande)** | Confidentiel affaires + données de tiers | Conformité, commerce, bureautique, messagerie | Sortie autorisée après consentement. Champs internes — marge, coût de revient, commentaires de gestion — exclus par défaut de toute correspondance. |
| **Identité et coordonnées de client** | Donnée personnelle | Conformité, commerce, messagerie, paiement | Minimisation obligatoire : seuls les champs exigés par l'opération partent. La correspondance de champs ne peut pas ajouter un champ non déclaré nécessaire. |
| **Montant et référence de règlement** | Donnée financière | Paiement, banque | Sortie autorisée. Aucun numéro de compte complet dans une trace ou une charge utile archivée. |
| **Rémunération et données de paie** | Personnelle sensible | Aucun | Interdiction absolue. Aucune liaison ne peut avoir pour source un objet du domaine Paie, à la seule exception de l'ordre de virement, qui expose un montant et un bénéficiaire sans aucun élément de rubrique. Vérifié en intégration continue. |
| **Données de production, nomenclature, coût** | Secret industriel | Aucun par défaut | Aucune liaison sortante native. L'API publique y donne accès si et seulement si le rôle du jeton le permet, sous la responsabilité du client. |
| **Journal d'audit et registre d'échange** | Preuve | Export de garantie de sortie uniquement | Jamais transmis à un tiers dans le cadre d'une liaison. Exportable intégralement par le client. |

### 9.3 Rétention des charges utiles

Le contenu échangé et l'enregistrement de l'échange ont des durées de vie différentes, et les confondre serait une faute. L'enregistrement — qui, quand, vers qui, avec quelle empreinte, quel verdict — est conservé aussi longtemps que la pièce métier qu'il concerne, donc jusqu'à dix ans pour ce qui touche à la facturation. La charge utile, elle, est conservée par défaut sur une durée courte, paramétrable, suffisante au diagnostic et au rejeu, puis purgée. Deux exceptions, portées par des paramètres versionnés plutôt que par du code : le document normalisé soumis à un dispositif fiscal et le verdict reçu, dont la conservation relève d'une durée réglementaire et non d'un confort d'exploitation.

### 9.4 Cadre malgache et transferts

Le traitement de données personnelles à Madagascar relève de la loi n° 2014-038 du 9 janvier 2015, complétée par un décret d'application, et le contrôle en est confié à la Commission malagasy de l'informatique et des libertés. Le pays a par ailleurs ratifié la convention régionale sur la cybersécurité et la protection des données. L'activité de l'autorité a été longtemps limitée par ses moyens et s'est intensifiée récemment.

Trois conséquences pratiques pour la Phase 4, sans que ce document ne constitue un avis juridique — l'hypothèse H27 est ouverte et doit être levée avec un conseil compétent avant la mise en production de la vague 4B.

- **Le client est responsable de traitement, l'éditeur est sous-traitant.** La documentation de mise en service doit énoncer cette répartition, lister les traitements et les destinataires, et fournir au client de quoi tenir son propre registre — ce que le registre d'échange lui donne déjà pour la partie sortante.
- **L'information préalable et le consentement sont portés par le mécanisme A7**, qui affiche les catégories et les destinataires avant activation et journalise la décision. C'est la raison pour laquelle A7 est un axe de personnalisation et non une option d'administration.
- **Les transferts hors du territoire doivent être identifiables**, ce qui suppose de connaître le pays d'établissement du tiers. Le catalogue de connecteurs porte cette information lorsqu'elle est publique et signale explicitement lorsqu'elle ne l'est pas ; un connecteur dont l'implantation est inconnue est signalé comme tel plutôt que présenté comme local.

## 10. UX et confort d'exploitation

*Représenter ce qui n'a pas encore abouti*

### 10.1 Le problème d'interface propre à la Phase 4

Les phases précédentes affichaient des états connus : une facture est validée ou ne l'est pas, un mouvement est passé ou ne l'est pas. La Phase 4 introduit une catégorie d'état que l'interface des Phases 1 à 3 ne sait pas représenter : **l'incertitude bornée**. Une soumission fiscale est partie mais n'a pas de verdict. Un paiement a été initié, le client dit avoir payé, la notification n'est pas arrivée. Un envoi a échoué trois fois et sera retenté dans deux heures.

La faute classique consiste à afficher ces situations comme des succès, parce qu'un point vert rassure, ou comme des erreurs, parce que c'est plus simple. Les deux détruisent la confiance : le premier fait découvrir le problème trop tard, le second fait appeler le support pour une situation normale. Le principe retenu, hérité de la règle posée en Phase 1 sur l'envoi de courriel — l'utilisateur voit l'état réel, jamais un faux succès — est étendu en une exigence plus forte : **tout état d'attente affiche ce qui va se passer ensuite et quand.**

### 10.2 Neuf composants nouveaux

| Composant | Rôle | Exigence propre |
|---|---|---|
| **Pastille d'état d'échange** | Affiche sur une pièce l'état de ses liaisons : en file, envoyé, accepté, rejeté, suspendu. | Quatre couleurs au maximum, un libellé toujours présent — la couleur seule ne porte jamais l'information. |
| **Bandeau d'attente** | Sur une pièce dont un échange est en cours : ce qui est attendu, de qui, et à quelle heure la prochaine tentative aura lieu. | Aucune formulation technique. « En attente de validation fiscale, nouvelle tentative à 14 h 30 » et non un code de statut. |
| **Fiche de liaison** | Écran de configuration d'une liaison : portée, correspondance, calendrier, politique d'échec, plafond. | Construite par le moteur de vues. Prévisualisation obligatoire sur un objet réel avant activation. |
| **Éditeur de correspondance** | Association champ source vers champ cible, avec transformations du jeu fermé. | Refuse à l'enregistrement toute correspondance incomplète sur un champ obligatoire du tiers, plutôt que d'échouer au premier envoi. |
| **Journal d'échange filtrable** | La liste des échanges, avec recherche par pièce, tiers, statut, période. | Data grid existant. Chaque ligne mène à sa pièce métier en un clic, et réciproquement. |
| **Panneau de rejeu** | Sélection d'échanges en échec et relance supervisée. | Affiche le nombre d'objets concernés et le coût estimé avant confirmation. Le rejeu de masse sans estimation est la première cause de facture surprise. |
| **Jauge de plafond** | Consommation face au plafond, par catégorie et par période. | Alerte à l'approche, pas seulement à l'atteinte. Un plafond atteint un 28 du mois sans avertissement est vécu comme une panne. |
| **Écran de consentement de sortie** | Activation d'un connecteur, avec les quatre informations de la section 9.1. | Le texte des catégories est généré depuis la déclaration de l'adaptateur, jamais rédigé à la main — sinon il devient faux à la première évolution. |
| **Assistant d'enrôlement** | Guide pas à pas de mise en service d'un connecteur : ce qu'il faut demander, à qui, et où le saisir. | Écrit pour un comptable, pas pour un informaticien. Vérification en direct avant activation, avec un message d'échec qui dit quoi corriger. |

### 10.3 Le vocabulaire de l'échec

Un connecteur produit des erreurs qui viennent d'ailleurs, formulées pour des développeurs. Les remonter telles quelles est la manière la plus sûre de rendre la console de flux inutilisable. Chaque adaptateur doit donc traduire les erreurs du tiers dans un jeu fermé de six familles, chacune associée à une action de reprise unique et compréhensible : identifiants à renouveler, donnée manquante ou invalide dans la pièce, refus motivé par le tiers, tiers indisponible, plafond atteint, anomalie à signaler à l'éditeur. Le message d'origine reste consultable pour le diagnostic, replié. Un adaptateur qui remonte une septième famille ne passe pas la recette.

## 11. Scalabilité

*La dimension dominante n'est plus le volume interne, c'est la dépendance externe*

| Dimension | Situation Phase 4 | Seuil où elle devient un problème | Option prévue |
|---|---|---|---|
| **Volume d'échanges** | Une à trois lignes par pièce sortante, plus les tentatives. Le connecteur fiscal et le paiement sont les contributeurs principaux. | Lenteur du journal filtrable ; fenêtre de purge dépassée ; croissance non maîtrisée de la charge utile. | Partitionnement mensuel dès la conception ; charge utile en table séparée avec rétention propre ; index ciblés sur pièce, liaison et statut ; archivage par exercice. |
| **Latence des tiers** | Dimension nouvelle et dominante. Un tiers lent immobilise un worker sans consommer de ressource. | File de sortie qui croît plus vite qu'elle ne se vide, sur un seul connecteur. | File dédiée isolée ; délai maximal par appel ; disjoncteur par connecteur et par tenant ; parallélisme borné par adaptateur pour ne pas déclencher les limitations de débit du tiers. |
| **Rafales entrantes** | Les notifications arrivent groupées : fin de journée de caisse, ouverture d'une plateforme après incident. | Point d'entrée qui répond trop lentement, provoquant la réémission par le tiers et l'amplification. | Accusé immédiat puis traitement en file ; déduplication par identifiant d'événement ; limitation de débit par adresse entrante. |
| **Nombre de connecteurs actifs** | Neuf familles, douze adaptateurs au plafond, chacun avec son rythme de rupture propre. | Déjà critique. Deux à quatre ruptures par an et par connecteur saturent la capacité d'un développeur seul (H28). | Plafond vérifié en intégration continue ; suite de contrats de test par adaptateur, exécutée quotidiennement contre l'environnement d'essai du tiers ; retrait assumé d'un connecteur de confort plutôt que dégradation de l'ensemble. |
| **Nombre de tenants** | Chaque tenant a ses propres secrets, ses propres plafonds et son propre enrôlement chez chaque tiers. | La mise en service devient le goulet, bien avant la technique : chaque nouveau client suppose plusieurs démarches externes. | Assistant d'enrôlement, vérification automatique de la configuration, et modèle par défaut par secteur. C'est un enjeu d'exploitation, pas de performance. |
| **Équipe de développement** | Une personne, quatre phases en production. Capacité de 3,5 jours effectifs par semaine. | Franchie. La tendance signalée en Phase 3 se confirme. | Deux vagues ; neuf blocs ; plafond d'adaptateurs ; API publique en substitut du développement spécifique ; arbitrage du support à trancher avant la fin de la vague 4A — c'est la troisième fois qu'il est reporté. |

### 11.1 Budgets d'architecture révisés

| Budget | Fin Phase 3 | Révisé Phase 4 | Justification |
|---|---|---|---|
| **Modèles** | 380 | 430 | ≈ 20 pour le socle de flux (connecteur, liaison, correspondance, planification, déclencheur, échange, charge utile, incident, quota, coût, idempotence, corrélation) ; ≈ 8 pour l'API publique et les webhooks ; ≈ 10 pour la conformité ; ≈ 8 pour le paiement et le rapprochement ; ≈ 4 pour les flux bancaires. Les adaptateurs eux-mêmes n'ajoutent aucun modèle — c'est la vérification que la décision structurante n° 2 est tenue. |
| **Endpoints** | 1 060 | 1 210 | Console de flux, points d'entrée de webhook par connecteur, et surtout la surface publique. Celle-ci est comptée séparément ci-dessous pour éviter qu'elle ne dilue le budget interne. |
| **Écrans (total)** | 245 | 278 | Console de flux, fiches de liaison, journal, rejeu, consentement, assistants d'enrôlement, plus les fragments greffés sur les écrans existants. |
| **Écrans legacy** | 0 | 0 — maintenu | Inchangé depuis la Phase 1. Aucun écran de la Phase 4 ne crée de dette d'interface. |
| **Rapports** | plafond Phase 3 | + 8 au maximum | Supervision des flux, coûts par connecteur, taux de rapprochement, conformité par période. Arbitrés au sprint 1, rapport par rapport, selon la règle des Phases 2 et 3. |
| **Rubriques de paie** | plafond Phase 3 | inchangé | La Phase 4 ne touche pas à la paie, à l'exception de l'ordre de virement, qui n'ajoute aucune rubrique. |
| **Adaptateurs (nouveau)** | — | 12 | Nouveau budget, le plus important de la phase. Un catalogue de connecteurs dérive exactement comme un catalogue de rapports ou une table de rubriques : chaque client apporte son cas particulier, personne ne retire jamais rien, et au bout de deux ans l'entretien consomme toute la capacité. Le plafond force à répondre par l'API publique plutôt que par un adaptateur de plus. |
| **Opérations publiques (nouveau)** | — | 80 | Nouveau budget. Surface exposée aux tiers, en lecture et en écriture, déclarée et versionnée. Elle est plafonnée séparément parce qu'elle a un coût de rétrocompatibilité que les endpoints internes n'ont pas : une opération publiée ne se retire plus, elle se déprécie sur plusieurs versions. |

**Cinquante modèles pour neuf familles de connecteurs, c'est peu — et c'est le test de l'architecture.** La Phase 3 avait ajouté quatre-vingt-quinze modèles pour cinq modules, parce qu'elle modélisait des réalités absentes du produit. La Phase 4 en ajoute cinquante pour neuf familles, parce qu'elle ne modélise qu'une seule réalité nouvelle — l'échange — et la décline. Si le décompte réel dérive au-delà de soixante-dix au sprint 20, ce n'est pas le budget qu'il faut rehausser : c'est le signe qu'un adaptateur a commencé à créer ses propres entités, et la revue de conception doit le corriger avant que le suivant ne s'en inspire.

## 12. Choix technologiques

*Trois décisions, toutes arbitrées par la charge d'exploitation d'une personne seule*

### 12.1 Orchestration : bus interne ou plateforme tierce

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Hub de flux interne, dans le monolithe** | Aucun composant nouveau à exploiter ; accès direct à la logique métier et aux permissions ; registre unique et cohérent avec le journal d'audit ; testable sans réseau. | Tout adaptateur est du code de l'éditeur ; pas de catalogue d'intégrations gratuit ; l'ajout d'un tiers exige un déploiement. | **Retenu.** |
| **Plateforme d'automatisation embarquée dans la pile** | Catalogue immédiat de plusieurs centaines d'intégrations ; interface visuelle appréciée ; auto-hébergeable, donc compatible avec l'argument de souveraineté. | Un second produit à exploiter, mettre à jour et sécuriser ; les flux échappent au registre et au journal d'audit ; les permissions du client ne s'y appliquent pas ; la charge mémoire entre en concurrence avec le modèle de langage local (H30). | Écarté comme composant du produit. Recommandé et documenté comme outil du client, branché sur l'API publique. |
| **Plateforme d'intégration en service, hébergée par un tiers** | Mise en service immédiate ; aucune exploitation ; catalogue le plus large du marché. | Toutes les données transitent hors du serveur du client, ce qui contredit frontalement la proposition de valeur ; coût variable non maîtrisé ; dépendance sur le chemin critique. | Écarté sans discussion. |
| **Courtier de messages dédié** | Découplage propre, débit élevé, réessai natif. | Un composant d'infrastructure de plus pour un volume qui ne le justifie pas. L'ordonnanceur en base livré en Phase 1 et les files de la Phase 2 suffisent. | Écarté. Réexamen si la file de sortie dépasse durablement le millier d'échanges en attente. |

### 12.2 Encaissement mobile : opérateur direct ou agrégateur

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Raccordement direct à chaque opérateur** | Coût unitaire le plus bas ; maîtrise complète du comportement et des délais ; pas d'intermédiaire dans la chaîne de preuve. | Trois enrôlements par tenant, trois formats, trois politiques de notification, trois sources de panne. Une seule interface est documentée publiquement (H22, H23). | Retenu comme option pour le tenant à fort volume, sur l'opérateur principal. |
| **Agrégateur local, interface unique** | Une seule intégration couvrant les trois opérateurs et parfois la carte ; mise en service courte ; versement périodique unique, plus simple à rapprocher. | Commission supplémentaire ; dépendance de plus ; le versement groupé complique le rapprochement de second niveau ; viabilité de l'acteur à évaluer (H24). | **Retenu comme mode par défaut.** |
| **Passerelle internationale** | Robustesse, documentation, portée multi-pays utile à l'expansion régionale. | Couverture locale de la monnaie électronique incertaine ou tarifée au niveau international ; peu adaptée au cas nominal malgache. | Écarté pour l'encaissement local. Envisageable pour la carte à l'export. |

**La décision réelle n'est pas le choix d'un fournisseur mais l'abstraction qui rend le choix réversible** : une interface unique de service d'encaissement, avec deux implémentations, sélectionnée par paramètre de tenant. Le surcoût de conception est d'environ un demi-sprint ; il vaut l'assurance de ne pas réécrire le bloc D si un acteur ferme ou change ses conditions.

### 12.3 Raccordement fiscal : direct ou par tiers de confiance

| Option | Analyse | Verdict |
|---|---|---|
| **Raccordement direct à la plateforme publique** | Coût marginal nul par document ; chaîne de preuve la plus courte ; suppose une habilitation dont la procédure est inconnue (H21). | **Cible retenue.** |
| **Passage par un opérateur agréé, là où ce régime existe** | Mise en conformité rapide et portée multi-pays ; surcoût par document ; dépendance sur un flux réglementaire, donc sur le chemin critique du client. | Repli, activable par paramètre si H21 se révèle bloquante. |
| **Attendre la publication des spécifications avant tout développement** | Zéro risque de retravail ; mais laisse le produit sans réponse le jour de l'ouverture, avec un délai de conformité qui court. | Écarté. Le moteur est construit sur la structure commune des dispositifs régionaux, le format est un paramètre. |

### 12.4 Briques confirmées sans réexamen

Django et son écosystème, l'interface de programmation interne, le rendu côté serveur avec améliorations progressives, PostgreSQL en base unique, l'isolation par discriminant et sécurité au niveau des lignes, l'ordonnanceur en base, le stockage objet de sauvegarde, le modèle de langage local avec repli optionnel, le déploiement par conteneurs sur serveur dédié : toutes ces décisions sont confirmées et ne sont pas rediscutées. La Phase 4 n'ajoute aucune dépendance d'exécution nouvelle en dehors des bibliothèques clientes strictement nécessaires aux protocoles des adaptateurs, chacune soumise à la même règle qu'en Phase 1 — une dépendance non maintenue est une dette, et son remplacement doit rester possible sans toucher au socle.

## 13. Socle de connectivité et modèle de flux

*Une seule écriture de flux, comme il n'y a qu'une écriture de stock*

### 13.1 L'échange comme écriture unique

Le parallèle avec la Phase 3 est délibéré et il structure tout le bloc A. De même que toute variation de quantité est une ligne de la table de mouvement, **toute interaction avec un tiers est une ligne de la table d'échange** : soumission fiscale, initiation de paiement, dépôt de fichier, publication de catalogue, notification reçue, appel d'API entrant, interrogation de référentiel. Aucun adaptateur ne tient son propre journal. La conséquence pratique est qu'une question comme « qu'est-ce qui est parti chez ce tiers cette semaine, et qu'est-ce qui a échoué » se répond par une requête sur une table, et non par la lecture de neuf journaux hétérogènes.

La contrepartie est une discipline stricte à l'écriture des adaptateurs, et elle est vérifiée mécaniquement : un test d'intégration continue analyse le code des adaptateurs et échoue si un appel réseau sortant est émis en dehors de l'exécuteur du hub. C'est l'équivalent, pour cette phase, du test qui interdit au gateway IA d'atteindre un endpoint hors liste blanche.

### 13.2 Entités du socle

| Entité | Rôle | Points d'attention de conception |
|---|---|---|
| **Connecteur** | Un tiers raccordable : type, version d'adaptateur, état, pays d'établissement, catégories de données concernées, opérations supportées. | Déclaratif. Les catégories de données affichées au consentement en sont dérivées, jamais saisies. |
| **Identifiant d'accès** | Les secrets d'un tenant pour un connecteur : chiffrés, portée, expiration, date de rotation. | Table à part, chiffrée, jamais exportée, jamais lue par le copilote. Empreinte partielle seule affichable. |
| **Liaison** | L'unité paramétrée par le client : connecteur + opération + type d'objet métier + sens + activation. | C'est l'objet que le client comprend. Un connecteur porte plusieurs liaisons ; une liaison ne porte qu'une opération. |
| **Correspondance** | Association champ source vers champ cible, avec transformation issue du jeu fermé. | Validée à l'enregistrement contre le schéma déclaré du tiers, pas au premier envoi. |
| **Planification** | Calendrier d'une liaison : fréquence, fenêtre, fuseau, jours d'exclusion. | Adossée au calendrier malgache paramétré en Phase 2. Fenêtres arbitrées par tenant pour ne pas concurrencer les traitements nocturnes de la Phase 3. |
| **Déclencheur** | Rattachement d'une liaison à une transition du moteur de workflow. | Effet de bord asynchrone. Ne peut jamais faire échouer la transition métier. |
| **Échange** | Le registre. Une ligne par tentative : tenant, liaison, sens, opération, pièce métier, empreinte, horodatage, statut, rang de tentative, coût imputé, clé de corrélation, clé d'idempotence, verdict. | Partitionné par mois dès la conception. Index sur pièce, liaison, statut et corrélation. Jamais modifié après écriture, sauf le statut, qui est une machine à états. |
| **Charge utile** | Le contenu émis et reçu, chiffré, avec sa propre rétention. | Table séparée. Sa purge ne détruit ni l'échange ni son empreinte. Rédaction des secrets à l'écriture. |
| **Incident** | Regroupement d'échecs répétés sur une liaison : famille d'erreur, première et dernière occurrence, état du disjoncteur, action de reprise proposée. | Objet avec chatter et workflow, comme les autres documents. C'est ce qui rend le support traçable. |
| **Quota et coût** | Plafond par tenant, catégorie et période ; consommation courante ; action au plafond. | Extension du compteur de la Phase 2. Les grilles tarifaires vivent dans les paramètres versionnés. |
| **Clé publique d'accès** | Jeton d'API d'un client tiers : portées, débit, expiration, révocation. | Portées exprimées en opérations publiques déclarées, jamais en tables. |
| **Abonnement de notification** | Souscription d'un client tiers à un événement sortant : adresse, secret de signature, filtres, politique de réessai. | Le pendant sortant du webhook entrant. Même moteur, sens inverse. |
| **Consentement de sortie** | Décision d'activation d'un connecteur : auteur, date, catégories affichées, révocation. | Immuable. Une révocation crée un nouvel enregistrement, elle n'efface pas le précédent. |
| **Rapprochement** | Lien entre un événement entrant et une pièce métier : règle appliquée, niveau de confiance, validation humaine éventuelle. | Porte les deux niveaux du bloc D : encaissement contre facture, puis versement groupé contre lot d'encaissements. |

### 13.3 Cycle de vie d'un échange

****Machine à états d'un échange****

```
                    ┌───────────┐
  déclenchement ───>│  PRÉPARÉ  │  contenu construit, empreinte
                    └─────┬─────┘  calculée, coût estimé
                          │ plafond vérifié · consentement vérifié
                          ▼
                    ┌───────────┐   plafond atteint   ┌────────────┐
                    │  EN FILE  │────────────────────>│  SUSPENDU  │
                    └─────┬─────┘                     └────────────┘
                          │ tentative n
                          ▼
                    ┌───────────┐  erreur transitoire ┌──────────────┐
                    │   ÉMIS    │────────────────────>│ À RÉESSAYER  │─┐
                    └─────┬─────┘                     └──────┬───────┘ │
          ┌───────────────┼───────────────┐                  │ seuil   │
          ▼               ▼               ▼                  ▼ atteint │
    ┌──────────┐   ┌────────────┐  ┌─────────────┐   ┌─────────────┐   │
    │ ACCEPTÉ  │   │  REJETÉ    │  │ EN ATTENTE  │   │  EN ÉCHEC   │   │
    │ verdict  │   │  motif     │  │ DE VERDICT  │   │ disjoncteur │   │
    │ conservé │   │ actionnable│  │             │   │   ouvert    │   │
    └──────────┘   └────────────┘  └──────┬──────┘   └──────┬──────┘   │
                                          │ notification    │ rejeu    │
                                          │ entrante (OP7)  │ supervisé│
                                          └─────────────────┴──────────┘
```

Trois propriétés de cette machine à états méritent d'être écrites parce qu'elles sont des sources classiques de défaut. **Accepté et rejeté sont terminaux** : un rejet ne se transforme pas en acceptation, il donne lieu à un nouvel échange après correction, et c'est ce qui rend la chronologie lisible pour un auditeur. **En attente de verdict peut durer indéfiniment sans être un échec**, et doit donc porter une échéance de relance plutôt qu'un délai d'expiration. **Suspendu pour cause de plafond n'est pas un échec technique** et ne doit pas ouvrir d'incident : il notifie et attend une décision.

### 13.4 Idempotence, corrélation et rejeu

- **Idempotence.** Chaque échange sortant porte une clé calculée sur la pièce, la liaison et le rang de tentative, transmise au tiers lorsqu'il l'admet. Un rejeu produit la même clé et ne crée donc pas de doublon chez le tiers. Là où le tiers ne gère pas l'idempotence, une vérification préalable de l'état est obligatoire avant toute réémission d'une opération d'argent — c'est la seule protection contre le double paiement.
- **Corrélation.** Une clé commune relie l'échange sortant, la notification entrante qui lui répond et la pièce métier concernée. Sans elle, un paiement notifié trois jours plus tard n'est plus rattachable à ce qui l'a déclenché, et le rapprochement automatique devient impossible.
- **Rejeu supervisé.** Toujours humain, jamais automatique au-delà de la politique d'échec configurée. Le panneau de rejeu affiche le volume et le coût estimé avant confirmation. Un rejeu crée de nouveaux échanges, il ne réécrit jamais les anciens : l'historique des tentatives est la pièce qui explique une facture de tiers.

### 13.5 Extension du modèle dimensionnel

L'entrepôt en étoile de la Phase 2 accueille une table de faits nouvelle — le fait d'échange — rattachée aux dimensions conformes existantes (temps, tenant, utilisateur, tiers, pièce) plus une dimension de connecteur. Cinq indicateurs rejoignent le dictionnaire gouverné : volume d'échanges par connecteur et par période, taux d'acceptation au premier envoi, délai médian d'obtention d'un verdict, taux de rapprochement automatique, coût par catégorie et par tenant. Comme en Phase 3, la condition posée est vérifiée et non supposée : le modèle doit accueillir ces faits sans reprise, ce qui est contrôlé au sprint 2.

## 14. Spécifications fonctionnelles — Phase 4

*Neuf familles, cinquante-quatre critères écrits pour devenir des tests*

### 14.1 F1 — Socle de flux et registre d'échange

**Contenu.** Catalogue de connecteurs déclaratif ; gestion chiffrée des identifiants d'accès avec rotation et alerte d'expiration ; liaisons paramétrées sur les sept axes de la section 4.3 ; éditeur de correspondance validé contre le schéma du tiers ; planification adossée au calendrier malgache ; déclencheurs sur transitions de workflow ; registre d'échange partitionné ; charge utile séparée et chiffrée avec rétention propre ; file de sortie persistante avec réessai espacé et disjoncteur par connecteur et par tenant ; incidents avec familles d'erreur normalisées ; rejeu supervisé ; idempotence et corrélation.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **FLX-1** | Un test d'intégration continue échoue si un adaptateur émet un appel réseau sortant en dehors de l'exécuteur du hub, ou si un échange est écrit sans empreinte de contenu. |
| **FLX-2** | Un échec de tiers sur un déclencheur événementiel n'empêche pas la transition métier : la facture est validée, l'échange est en file, et l'utilisateur voit l'état réel. |
| **FLX-3** | Après N échecs consécutifs sur une liaison, le disjoncteur s'ouvre, les échanges suivants restent en file sans appel réseau, et un incident unique est créé — pas un incident par tentative. |
| **FLX-4** | Un rejeu d'un échange sortant transmet la même clé d'idempotence et ne crée aucun doublon chez un tiers d'essai qui la respecte. |
| **FLX-5** | La purge de la charge utile d'un échange laisse l'échange, son empreinte, son horodatage et son verdict intacts et interrogeables. |
| **FLX-6** | Une correspondance de champs incomplète sur un champ déclaré obligatoire par le tiers est refusée à l'enregistrement, avec désignation du champ manquant. |
| **FLX-7** | Un test d'isolation à deux tenants vérifie qu'aucun échange, secret, liaison ou charge utile d'un tenant n'est atteignable depuis l'autre, y compris par identifiant direct. |
| **FLX-8** | Un motif ressemblant à un secret n'apparaît dans aucun journal, aucune charge utile archivée et aucun message d'erreur affiché à l'utilisateur. |

### 14.2 F2 — API publique, webhooks et quotas

**Contenu.** Surface REST versionnée, décrite en OpenAPI et publiée ; clés par tenant avec portées exprimées en opérations déclarées, débit maximal et expiration ; environnement d'essai avec jeu de données isolé ; journal d'appel consultable par le client ; notifications sortantes signées, avec abonnement, filtres, réessai et rejeu ; points d'entrée de webhook par connecteur, avec signature, fenêtre d'horodatage et déduplication ; politique de dépréciation écrite.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **API-1** | Un jeton client ne peut obtenir aucune donnée qu'un utilisateur du rôle correspondant ne pourrait consulter dans l'interface (test avec un jeton de portée commerciale interrogeant des données comptables et de paie). |
| **API-2** | Aucune opération non déclarée dans la liste blanche publique n'est atteignable par un jeton client, même si l'endpoint interne existe. |
| **API-3** | Un appel de webhook non signé, mal signé ou horodaté hors fenêtre est rejeté sans traitement, et journalisé sans révéler le motif à l'appelant. |
| **API-4** | Un même événement entrant reçu deux fois produit un seul traitement métier et deux lignes de registre, la seconde marquée comme doublon. |
| **API-5** | Le point d'entrée de webhook accuse réception en moins de 500 ms sous charge nominale, le traitement étant différé en file. |
| **API-6** | La révocation d'une clé est effective immédiatement, y compris pour les appels en cours d'authentification. |
| **API-7** | Le dépassement du débit d'une clé produit une réponse normalisée avec délai d'attente indiqué, et n'affecte ni les autres clés du tenant ni les autres tenants. |

### 14.3 F3 — Conformité e-facture et clearance

**Contenu.** Moteur de dispositif à contrôle continu, paramétré par pays : production du document structuré normalisé depuis la facture du module Sales, contrôles de complétude préalables, signature avec un certificat fourni par le client, soumission, attente et réception du verdict, conservation de l'identifiant attribué et du marquage vérifiable, apposition sur la représentation lisible, archivage à durée réglementaire, gestion du rejet avec motif actionnable, de l'annulation et de l'avoir, mode d'attente lorsque aucun raccordement n'est ouvert, et reprise sans perte à l'ouverture. Le référentiel de formats et de durées vit dans les paramètres versionnés.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **EFA-1** | Une facture validée produit un document structuré conforme au schéma paramétré, contrôlé avant soumission ; un champ obligatoire manquant bloque la soumission et désigne le champ, sans invalider la facture. |
| **EFA-2** | En l'absence de raccordement ouvert, le document est produit, signé, archivé et mis en file ; aucune erreur n'est présentée à l'utilisateur, et un bandeau indique l'état d'attente. |
| **EFA-3** | L'ouverture d'un raccordement provoque le rejeu de la file en attente dans l'ordre chronologique, sans perte, sans doublon et sans intervention manuelle autre que la confirmation initiale. |
| **EFA-4** | Le verdict reçu est conservé dans sa forme d'origine, en plus de son interprétation ; l'identifiant attribué et le marquage vérifiable sont reportés sur la représentation lisible du document. |
| **EFA-5** | Un rejet affiche un motif actionnable par un comptable et propose une reprise ; la correction produit un nouvel échange, jamais une modification de l'échange rejeté. |
| **EFA-6** | Une facture peut être encaissée avant d'avoir obtenu son verdict, et un verdict peut arriver après l'encaissement, sans incohérence de statut ni blocage comptable. |
| **EFA-7** | Le changement de pays du paramétrage bascule format, contrôles, durée d'archivage et libellés, sans déploiement de code. |
| **EFA-8** | L'expiration prochaine du certificat de signature déclenche une alerte au moins trente jours avant échéance ; une signature avec certificat expiré est refusée avant soumission. |

### 14.4 F4 — Encaissement mobile et rapprochement

**Contenu.** Interface unique de service d'encaissement, avec deux implémentations — agrégateur par défaut, raccordement direct en option de tenant. Création d'une intention de règlement depuis une facture ou un ticket de caisse ; production d'un lien et d'un code de règlement transmissibles par le canal de messagerie ou affichables au comptoir ; réception de la notification de paiement ; rapprochement automatique de premier niveau avec la pièce d'origine ; écriture comptable de contrepartie via le référentiel de la Phase 1 ; rapprochement de second niveau du versement groupé de l'agrégateur, commission comprise ; traitement des paiements orphelins, des doublons et des montants partiels ; remboursement par contre-écriture tracée.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **PAY-1** | Le basculement d'un tenant entre agrégateur et raccordement direct s'effectue par paramètre, sans modification de code et sans reprise des intentions en cours. |
| **PAY-2** | Une notification de paiement reçue est rapprochée automatiquement de la pièce d'origine dans le cas nominal, et produit l'écriture d'encaissement sans intervention comptable. |
| **PAY-3** | Un paiement reçu sans correspondance est placé en attente de rapprochement, visible dans un écran dédié, et ne produit aucune écriture tant qu'il n'est pas affecté. |
| **PAY-4** | Une double notification du même paiement produit un seul encaissement et une seule écriture. |
| **PAY-5** | Un versement groupé de l'agrégateur est rapproché du lot d'encaissements qu'il couvre, la commission étant isolée sur son propre compte de charge. |
| **PAY-6** | Un montant partiel produit un encaissement partiel et laisse la pièce ouverte pour le solde, sans lettrage forcé. |
| **PAY-7** | Le rejeu d'une intention de règlement vérifie l'état auprès du tiers avant toute réémission ; aucun double débit n'est possible dans le scénario de test de réémission après temporisation. |
| **PAY-8** | Le taux de rapprochement automatique est calculé, publié comme indicateur gouverné et consultable par période et par connecteur. |

### 14.5 F5 — Flux bancaires et trésorerie

**Contenu.** Import de relevé multi-format avec correspondance de colonnes paramétrable en repli ; détection de période déjà chargée ; moteur de règles de rapprochement — montant, référence, tiers, date, avec tolérance paramétrable — produisant des propositions et non des écritures ; lettrage assisté ; production et export d'ordres de virement, y compris pour la paie, avec suivi d'état de remise ; réconciliation des comptes d'attente ; alimentation de la prévision de trésorerie de la Phase 2 par le solde réel.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **BNK-1** | Le rechargement d'un relevé déjà importé ne crée aucun doublon de ligne et le signale explicitement. |
| **BNK-2** | Une ligne de relevé en anomalie n'interrompt pas le chargement du lot ; elle est isolée dans un rapport de chargement exploitable. |
| **BNK-3** | Le moteur de rapprochement produit des propositions horodatées avec un niveau de confiance ; aucune écriture comptable n'est créée sans validation, conformément à l'interdit de la section 4.4. |
| **BNK-4** | Un ordre de virement exporté est rattaché aux pièces qu'il règle, et son état de remise est suivi jusqu'au rapprochement du débit correspondant. |
| **BNK-5** | L'ordre de virement de paie n'expose que bénéficiaire, montant et référence : aucune donnée de rubrique n'est présente dans le fichier produit, vérifié par un test sur le contenu généré. |

### 14.6 F6 — Bureautique, stockage et calendrier

**Contenu.** Deux adaptateurs de suite, quatre opérations chacun : dépôt de documents et d'archives dans un espace de stockage du client avec arborescence et nommage paramétrables ; publication d'un jeu de données dans une feuille de calcul, en remplacement ou en ajout différentiel ; envoi de courriel par délégation authentifiée depuis l'adresse du client, en complément du serveur d'envoi de la Phase 1 ; publication d'événements d'exploitation — échéance de règlement, audit qualité, date d'arrêté de paie — dans un agenda. Plus un adaptateur de partage local pour le dépôt de fichiers sur une ressource de l'entreprise.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **BUR-1** | Le raccordement fonctionne avec un compte individuel autorisé par délégation, sans exiger d'annuaire d'entreprise administré. |
| **BUR-2** | La révocation de l'autorisation côté tiers est détectée, ouvre un incident de la famille « identifiants à renouveler » et n'entraîne aucun échec silencieux. |
| **BUR-3** | La publication différentielle d'un jeu de données n'écrase pas les colonnes ajoutées par le client dans la feuille de calcul cible. |
| **BUR-4** | L'indisponibilité du tiers bascule le dépôt sur le stockage objet de la Phase 1, avec notification et reprise automatique ultérieure. |
| **BUR-5** | Aucun champ classé secret industriel ou donnée de paie ne peut être sélectionné comme source d'une liaison de cette famille, quel que soit le paramétrage. |

### 14.7 F7 — Commerce et canaux de vente

**Contenu.** Connecteur générique plutôt qu'adaptateur par plateforme : publication du catalogue et des disponibilités depuis le stock de la Phase 3, ingestion des commandes vers un document au statut initial, retour du statut d'expédition, gestion des correspondances d'articles entre référentiel interne et référence de boutique, et traitement des écarts de prix et de disponibilité.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **COM-1** | Une commande ingérée crée un document au statut initial et ne produit ni facture, ni mouvement de stock, ni écriture, conformément à l'interdit de la section 4.4. |
| **COM-2** | Un article de boutique sans correspondance dans le référentiel interne place la commande en anomalie sans bloquer l'ingestion des autres. |
| **COM-3** | La publication de disponibilité reflète le stock disponible à la vente au sens de la Phase 3, réservations déduites, et non le stock physique. |
| **COM-4** | Une commande reçue en double, identifiée par sa référence de boutique, ne crée qu'un seul document. |

### 14.8 F8 — Messagerie étendue

**Contenu.** Mise à niveau de l'adaptateur livré en Phase 2 sur le modèle de facturation au message délivré, avec catégories par pays de destinataire ; migration ou coexistence des unités de coût historiques selon l'arbitrage de H26 ; extension des usages aux notifications de flux — mise à disposition d'une facture validée avec son marquage, avis de règlement reçu, relance sur échéance — dans le respect des modèles approuvés et du consentement déjà gérés.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **MSG-1** | Le coût est imputé au message délivré selon la grille paramétrée et la catégorie applicable ; aucun tarif n'est présent dans le code. |
| **MSG-2** | Les historiques antérieurs à la bascule restent lisibles dans leur unité d'origine, avec une date de changement d'unité visible dans les restitutions. |
| **MSG-3** | L'indisponibilité du canal ne bloque aucun processus : le courriel reste disponible en repli manuel et l'ERP demeure intégralement fonctionnel. |

### 14.9 F9 — Console de flux et gouvernance

**Contenu.** Tableau de bord des échanges adossé aux indicateurs gouvernés ; journal filtrable relié aux pièces métier ; catalogue des connecteurs avec état, version d'adaptateur et pays d'établissement ; écrans de consentement de sortie et de révocation ; jauges de plafond avec alerte anticipée ; panneau de rejeu avec estimation ; assistants d'enrôlement ; export intégral de garantie de sortie.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **CON-1** | Depuis toute pièce métier, l'état de ses échanges est atteignable en un clic, et réciproquement depuis toute ligne du journal. |
| **CON-2** | L'activation d'un connecteur exige un consentement affichant catégories de données, tiers, pays et durée de conservation connue ; la décision est journalisée avec son auteur. |
| **CON-3** | Une révocation coupe le connecteur immédiatement, conserve les échanges passés et propose la purge des charges utiles restantes. |
| **CON-4** | Le panneau de rejeu affiche volume et coût estimé avant confirmation ; aucun rejeu de masse n'est déclenchable sans cette estimation. |
| **CON-5** | Une alerte est émise à l'approche d'un plafond, avant son atteinte, au destinataire configuré. |
| **CON-6** | L'export de garantie de sortie produit l'intégralité des liaisons, échanges, verdicts et rapprochements dans un format documenté et relisible sans WideHalo. |

## 15. Modèle économique des connecteurs

*Ce qui est inclus, ce qui s'abonne, ce qui se compte*

Un connecteur n'a pas la même économie selon qu'il coûte à l'éditeur une charge d'entretien, une redevance de tiers, ou un coût par opération. Les confondre conduit soit à offrir ce qui coûte, soit à facturer ce qui ne coûte rien — et les deux abîment la relation client. Trois régimes sont donc définis, et le régime d'un connecteur est un attribut de son catalogue, pas une négociation commerciale.

### 15.1 Trois régimes tarifaires

| Régime | Ce qu'il couvre | Connecteurs concernés | Justification |
|---|---|---|---|
| **Socle inclus** | Compris dans l'abonnement de base, sans limite d'usage autre que technique. | API publique et notifications sortantes, exports fichiers, stockage objet, partage local, courriel, bureautique et stockage, commerce générique, import de relevé bancaire. | Aucun coût marginal pour l'éditeur, et ce sont précisément les connecteurs qui rendent le produit intégrable. Les facturer découragerait l'usage qui installe le produit au centre du système d'information. |
| **Abonnement de module** | Supplément mensuel par tenant, indépendant du volume. | Conformité e-facture. Le cas échéant, un second pays de conformité. | Le coût est un coût de veille et d'entretien réglementaire, pas un coût par document. L'abonnement finance la capacité à suivre un texte qui change, ce qui est exactement ce que le client achète (H29). |
| **À l'usage** | Refacturation du coût du tiers, majorée d'une marge de traitement déclarée. | Messagerie conversationnelle, encaissement mobile, passerelle de carte, envoi de messages courts. | Le coût est directement proportionnel à l'usage et supporté par l'éditeur ou par le tenant selon le contrat. Le compteur de la Phase 2, généralisé, le rend visible avant qu'il ne surprenne. |

### 15.2 Règles de facturation à l'usage

- **Aucun tarif dans le code.** Grilles, catégories, devises, marges et dates d'entrée en vigueur sont des paramètres versionnés, au même titre que les barèmes fiscaux de la Phase 1. Un changement de tarif d'un opérateur est une mise à jour de paramètre, pas une version du logiciel.
- **Coût imputé au moment de l'échange**, sur la ligne du registre, avec la version de grille appliquée. Recalculer a posteriori un coût passé est impossible et doit l'être : c'est ce qui rend une facture explicable.
- **Plafond obligatoire avant activation.** Aucun connecteur du régime à l'usage ne peut être activé sans qu'un plafond ne soit défini. La valeur par défaut est volontairement basse.
- **Plafond atteint : suspension notifiée.** Les échanges passent au statut suspendu, l'utilisateur est averti, et la reprise est une décision explicite. Jamais d'échec silencieux, jamais de dépassement automatique.
- **Estimation avant action de masse.** Tout rejeu ou envoi groupé affiche le coût estimé avant confirmation.
- **Restitution mensuelle par tenant**, par connecteur et par catégorie, exportable, réconciliable avec la facture du tiers. C'est la condition pour que le client accepte le modèle.

### 15.3 Ce que le régime tarifaire impose au produit

Le choix d'un modèle à l'usage n'est pas neutre techniquement, et trois exigences en découlent, toutes déjà inscrites dans les critères de la section 14. La première est la précision de l'imputation : un coût attribué à la mauvaise pièce ou au mauvais tenant devient un litige. La deuxième est l'idempotence stricte, parce qu'un doublon d'envoi est un doublon de facture. La troisième est la lisibilité du journal : le client doit pouvoir reconstituer sa consommation ligne à ligne, sans quoi il contestera le total. Ces trois exigences valent pour tous les connecteurs, y compris ceux du socle inclus, puisque le régime d'un connecteur peut changer.

## 16. Plan de développement — sprints hebdomadaires

*Trente-quatre sprints, deux vagues, un jalon dicté par l'extérieur*

### 16.1 Ordonnancement et dépendances

Trois contraintes d'ordonnancement gouvernent le plan. Premièrement, le bloc A ne livre rien de visible et conditionne tout : aucun connecteur ne démarre avant que le registre, la file et le rejeu ne soient éprouvés. Deuxièmement, le bloc C — conformité — vient tôt malgré son incertitude, parce que son calendrier n'appartient pas à l'éditeur ; il est placé immédiatement après l'API publique, dont il consomme la surface entrante pour les verdicts asynchrones. Troisièmement, les blocs de confort sont placés en fin de vague 4B, à l'endroit où ils peuvent être raccourcis si l'un des blocs amont dérive.

****Chaîne des blocs et découpage en vagues****

```
  S1→S6    S7→S9   S10→S16  ┃  S17→S22  S23→25 S26→29 S30→31 S32→33  S34
┌─────────┬────────┬────────╂─┬────────┬───────┬──────┬──────┬───────┬─────┐
│ A SOCLE │ B API  │ C CON- ┃ │ D PAIE-│ E FLUX│ F BU-│ G CO-│ H CON-│  I  │
│ DE FLUX │PUBLIQUE│FORMITÉ ┃ │ MENT   │BANCAI-│REAUTI│MMERCE│ SOLE  │ MEP │
│         │WEBHOOKS│E-FACT. ┃ │ MOBILE │  RES  │ QUE  │      │ COÛTS │     │
└─────────┴────────┴────────╂─┴────────┴───────┴──────┴──────┴───────┴─────┘
  ◀──────── VAGUE 4A ──────▶ ┃ ◀──────────────── VAGUE 4B ─────────────────▶
                    JALON J4 — MISE EN PRODUCTION 4A (S16)
```

### 16.2 Blocs A à I

| Bloc | Contenu | Sprints | Livrable de fin de bloc et point de contrôle |
|---|---|---|---|
| **A** | Socle de flux, registre, file, incidents, rejeu, cadrage | S1 – S6 | Registre partitionné et éprouvé sur un adaptateur factice couvrant les huit opérations. Contrôle au sprint 2 : le modèle dimensionnel de la Phase 2 accueille le fait d'échange sans reprise. Arbitrage des rapports ajoutés au sprint 1. |
| **B** | API publique, webhooks, clés, portées, quotas, bac à sable | S7 – S9 | Surface publiée en OpenAPI, jeu de tests de conformité, environnement d'essai ouvert. Vérification de H30 au sprint 9. |
| **C** | Conformité e-facture et clearance | S10 – S16 | Moteur paramétré par pays, opérationnel en mode d'attente et rejouable. Levée de H20 et H21 au sprint 10 au plus tard ; à défaut, bascule sur le repli de la section 12.3. Jalon J4 — mise en production de la vague 4A au sprint 16. |
| **D** | Encaissement mobile et rapprochement | S17 – S22 | Interface unique à deux implémentations, rapprochement à deux niveaux, taux publié. Levée de H22, H23 et H24 au sprint 15, donc avant le démarrage du bloc. |
| **E** | Flux bancaires et trésorerie | S23 – S25 | Import multi-format, moteur de règles, ordres de virement, alimentation de la prévision de trésorerie. Levée de H25 au sprint 22. |
| **F** | Bureautique, stockage, agenda, partage local | S26 – S29 | Deux adaptateurs de suite à quatre opérations, plus le partage local. Premier bloc raccourcissable en cas de dérive amont. |
| **G** | Commerce et canaux de vente | S30 – S31 | Connecteur générique, correspondances d'articles, ingestion et retour de statut. |
| **H** | Console de flux, coûts, plafonds, mise à niveau messagerie | S32 – S33 | Tableau de bord, jauges, consentements, export de garantie de sortie, bascule de l'unité de coût de la messagerie (H26, arbitrée au sprint 3). |
| **I** | Durcissement et mise en production | S34 | Scénario « tout coupé », charge sur les rafales entrantes, revue de sécurité de la surface publique. Jalon J5 — mise en production de la vague 4B. |

### 16.3 Répartition du travail entre l'humain et l'assistant

| Nature de la tâche | Portée par | Motif |
|---|---|---|
| **Adaptateurs de protocole, correspondances, sérialisation, tests de contrat** | Assistant, revue légère | Travail répétitif et bien cadré, à fort rendement. C'est la part de la phase où le gain est le plus élevé. |
| **Écrans de console, fiches de liaison, journal, jauges** | Assistant, revue légère | Dérivés du moteur de vues et du data grid. Aucun composant conceptuellement nouveau. |
| **Machine à états de l'échange, idempotence, corrélation, disjoncteur** | Assistant, revue approfondie | Code court mais dont les défauts sont silencieux et coûteux. La relecture y vaut plus que la génération. |
| **Règles de rapprochement, traitement des cas limites de paiement** | Humain, assisté | La difficulté est métier et non technique. Les cas limites viennent de l'observation du terrain, pas de la documentation d'un tiers. |
| **Lecture des textes réglementaires, formats normalisés, durées d'archivage** | Humain seul | Ni délégable, ni décidable par l'éditeur. C'est l'équivalent, pour cette phase, du recueil des règles de paie en Phase 3. |
| **Enrôlements, habilitations, contrats marchands** | Humain seul, avec le client | Démarches administratives dont le délai n'appartient à personne. À engager quatre sprints en avance. |

## 17. Estimation détaillée

*La phase la plus courte des quatre, sur la capacité la plus faible*

### 17.1 Hypothèses de l'estimation

- Un seul développeur, maîtrisant un socle qu'il a construit sur trois phases, découvrant la conformité fiscale électronique et les protocoles de monnaie électronique — deux domaines où la difficulté est documentaire et administrative plutôt que technique.
- **3,5 jours de travail effectif par semaine**, contre 4 en Phase 3 : le support couvre désormais trois phases en production. C'est la valeur annoncée en repère de la section 15.3 de la Phase 3, et elle est retenue telle quelle plutôt qu'optimisée.
- Les lots transverses — environnement, tests, intégration continue, documentation, gestion de projet — sont inclus dans les chiffres par sprint.
- Les enrôlements, habilitations et contrats auprès des tiers ne sont pas du développement, mais ils consomment de la supervision : ils sont comptés dans les blocs C et D.
- La documentation publique de l'API et le guide d'intégration sont inclus dans le bloc B. Les négliger reviendrait à livrer une surface que personne n'utilise.
- Le chiffrage suppose que les tiers retenus offrent un environnement d'essai. Un tiers sans environnement d'essai coûte environ un sprint supplémentaire à lui seul et doit être écarté à ce titre.

### 17.2 Synthèse par bloc

| Bloc | Sprints | J/H — voie classique | J-Token — génération | J/H — supervision |
|---|---|---|---|---|
| **A — Socle de flux et cadrage** | S1–S6 | 26 | 11 | 10 |
| **B — API publique et webhooks** | S7–S9 | 14 | 6 | 5 |
| **C — Conformité e-facture** | S10–S16 | 25 | 11 | 14 |
| **D — Encaissement mobile** | S17–S22 | 25 | 11 | 10 |
| **E — Flux bancaires** | S23–S25 | 14 | 6 | 5 |
| **F — Bureautique et stockage** | S26–S29 | 18 | 8 | 6 |
| **G — Commerce** | S30–S31 | 9 | 4 | 3 |
| **H — Console, coûts et plafonds** | S32–S33 | 9 | 4 | 3 |
| **I — Durcissement et production** | S34 | 5 | 2 | 2 |
| **Total Phase 4** | **34** | **145** | **63** | **58** |

Le bloc C est le seul dont la supervision humaine (14 J/H) dépasse nettement la génération (11 J-Token), et le déséquilibre est de même nature que celui du bloc Paie en Phase 3 : écrire un moteur de soumission est un travail cadré, établir ce qu'il faut soumettre, dans quel format, avec quelles mentions et quelle durée d'archivage relève de la lecture de textes et de la validation par un tiers. Aucun assistant ne porte ce travail, et c'est aussi celui dont le délai ne dépend pas de l'éditeur.

### 17.3 Comparaison avec les Phases 1 à 3

| Indicateur | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Lecture |
|---|---|---|---|---|---|
| **Sprints** | 29 | 22 | 38 | 34 | Périmètre plus étroit que la Phase 3 en surface fonctionnelle, mais plus large en surface d'exposition. |
| **J/H par sprint** | 5,9 | 6,0 | 4,9 | 4,3 | La baisse suit celle de la capacité hebdomadaire, pas une baisse d'intensité. |
| **Rapport J/H ÷ J-Token** | 2,30 | 2,40 | 2,35 | 2,30 | Stable. Le gain élevé sur les adaptateurs compense la perte sur la conformité et le rapprochement. |
| **Supervision ÷ J-Token** | 0,81 | 0,83 | 0,90 | 0,92 | En hausse continue. La relecture domine partout où l'erreur est silencieuse ou irréversible. |
| **Nouveaux composants UI** | ~20 | 9 | 12 | 9 | Retour au niveau de la Phase 2 : la console est majoritairement dérivée du socle. |
| **Capacité hebdomadaire** | 5 j | 4,5 j | 4 j | 3,5 j | Quatrième baisse consécutive. Le levier n'a pas été actionné à l'issue de la Phase 3. |

**La capacité est passée de 5 à 3,5 jours en trois phases, et l'arbitrage a été reporté deux fois.** La Phase 3 avait posé la question et proposé trois leviers : industrialiser le support, le déléguer même à temps partiel, ou accepter le passage en régime de maintenance. La Phase 4 aggrave le problème d'une manière qu'il faut nommer : un connecteur en panne est un incident perçu comme urgent par le client, qui survient quand le tiers le décide, et non quand l'éditeur est disponible. Ajouter neuf familles de connecteurs sans avoir traité la question du support revient à convertir une tendance en incident. À capacité constante de décroissance, une Phase 5 se ferait à trois jours effectifs, ce qui n'est plus un projet de développement mais un projet de maintenance déguisé. La décision doit être prise avant le jalon J4, et non après.

### 17.4 Trois scénarios

| Scénario | J/H classique | J-Token | Supervision | Durée | Ce qui le déclenche |
|---|---|---|---|---|---|
| **Optimiste** | 118 | 51 | 46 | 28 sem. | Le raccordement fiscal est ouvert et documenté à temps (H20, H21) ; un agrégateur accepte un contrat éditeur (H24) ; les relevés bancaires sont analysables sans correspondance manuelle (H25) ; l'unité de coût de la messagerie bascule sans coexistence (H26). |
| **Réaliste** | 145 | 63 | 58 | 34 sem. | Scénario de référence du plan de la section 16. |
| **Pessimiste** | 206 | 89 | 84 | 49 sem. | Le raccordement fiscal reste fermé et impose un repli par tiers de confiance ; chaque tenant doit s'enrôler individuellement auprès de chaque opérateur de monnaie électronique ; les relevés exigent une correspondance par banque ; deux unités de coût de messagerie coexistent ; une rupture d'interface majeure survient sur un connecteur livré et impose une reprise en cours de phase. |

## 18. Risques et plan de mitigation

*Sept risques sur dix viennent de l'extérieur — c'est la signature de cette phase*

| Réf. | Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|---|
| **P4-R1** | Le raccordement fiscal n'ouvre pas dans la fenêtre de la vague 4A, ou ouvre avec des spécifications éloignées de la structure anticipée. | Élevée | Élevé | Le mode d'attente est le livrable, pas une dégradation : document produit, signé, archivé, mis en file, rejouable sans perte (EFA-2, EFA-3). Le format est un paramètre. Repli par tiers de confiance prévu en 12.3. |
| **P4-R2** | Une rupture d'interface d'un tiers casse un connecteur en production, un jour non ouvré. | Certaine à l'échelle de l'année | Moyen à élevé | Suite de tests de contrat par adaptateur, exécutée quotidiennement contre l'environnement d'essai du tiers ; disjoncteur qui met en file au lieu d'échouer ; dégradation en saisie manuelle documentée pour chaque connecteur ; plafond de douze adaptateurs pour borner l'exposition (H28). |
| **P4-R3** | Double encaissement ou double facturation d'un tiers à la suite d'un rejeu mal maîtrisé. | Moyenne | Très élevé | Idempotence stricte, vérification d'état avant réémission sur toute opération d'argent (PAY-7), déduplication des événements entrants (API-4), estimation obligatoire avant rejeu de masse (CON-4). |
| **P4-R4** | Fuite de secrets de tiers, par journal, export, message d'erreur ou sauvegarde. | Faible | Très élevé | Chiffrement au repos avec clé hors base, non-lisibilité après saisie, filtre de rédaction sur toutes les traces avec test dédié (FLX-8), exclusion des secrets de tout export. |
| **P4-R5** | Le client découvre une facture de tiers supérieure à ce qu'il attendait. | Moyenne | Moyen | Plafond obligatoire avant activation, alerte anticipée (CON-5), imputation à l'échange avec version de grille, restitution mensuelle réconciliable, estimation avant action de masse. |
| **P4-R6** | Un enrôlement administratif non engagé à temps bloque un bloc prêt à être livré. | Élevée | Moyen | Démarches engagées quatre sprints avant le bloc concerné et inscrites en suites immédiates ; assistant d'enrôlement qui rend la démarche explicite au client dès la mise en service. |
| **P4-R7** | L'API publique est utilisée pour contourner la logique métier ou extraire massivement des données. | Moyenne | Élevé | Traversée obligatoire de la couche de services, portées par opération déclarée (API-2), quotas et débit par clé, journal d'appel consultable par le client, révocation immédiate (API-6). |
| **P4-R8** | La console de flux devient un écran que personne ne consulte, et les échecs s'accumulent silencieusement. | Moyenne | Élevé | Vocabulaire d'échec fermé à six familles avec action de reprise unique ; notification au destinataire configuré plutôt qu'attente de consultation ; indicateur de profondeur de file supervisé côté exploitation. |
| **P4-R9** | Le client attend des connecteurs non livrés — télédéclaration, douane, plateforme spécifique — et le découvre en recette. | Élevée | Moyen | Reprise mot pour mot des exclusions de la section 2.6 dans l'offre commerciale, avec la matrice de la section 3.9 comme support d'explication. C'est la reconduction directe du risque P3-R8. |
| **P4-R10** | La charge de support des connecteurs absorbe la capacité résiduelle et le produit s'arrête de fait après la Phase 4. | Élevée | Élevé | Arbitrage du support avant le jalon J4 (section 17.3) ; plafond d'adaptateurs ; refus assumé du développement spécifique ; retrait d'un connecteur de confort préféré à la dégradation générale. |

## 19. Critères de recette et métriques de succès

*Ce qui doit être vrai pour que la phase soit livrée*

### 19.1 Recette fonctionnelle

Les cinquante-quatre critères de la section 14 sont écrits pour être traduits en tests automatisés. La recette fonctionnelle ajoute quatre scénarios de bout en bout, exécutés manuellement au moins une fois par vague, sur des données réelles anonymisées.

- **Scénario nominal complet.** Une facture est validée, soumise, validée par le tiers, marquée, transmise au client par messagerie, réglée par monnaie électronique, rapprochée automatiquement, puis retrouvée dans le versement groupé du relevé bancaire. Chaque étape est traçable dans le registre par une seule clé de corrélation.
- **Scénario dégradé.** Le même parcours, avec la plateforme fiscale indisponible, l'agrégateur en erreur et la messagerie en échec. La facture est validée, encaissée en espèces au comptoir et comptabilisée. Aucun blocage, aucun faux succès, trois incidents ouverts et lisibles.
- **Scénario « tout coupé ».** Tous les connecteurs désactivés. Les parcours de référence des Phases 1 à 3 sont exécutés intégralement. C'est le scénario qui valide la décision structurante n° 7, et son échec est bloquant sans discussion possible.
- **Scénario de reprise.** Après quarante-huit heures d'indisponibilité simulée d'un tiers, la file est rejouée sans perte, sans doublon et dans l'ordre, avec un coût conforme à l'estimation affichée avant rejeu.

### 19.2 Recette technique — barrières bloquantes

| Barrière | Vague | Seuil |
|---|---|---|
| **Budgets d'architecture** | 4A et 4B | Modèles ≤ 430, endpoints ≤ 1 210, écrans ≤ 278, écrans legacy = 0, adaptateurs ≤ 12, opérations publiques ≤ 80, rapports ≤ plafond. Un dépassement fait échouer la construction. |
| **Confinement des appels sortants** | 4A | Aucun appel réseau hors exécuteur du hub ; aucun échange sans empreinte ; vérifié par analyse du code et test d'exécution. |
| **Isolation entre tenants** | 4A | Zéro fuite sur échanges, secrets, liaisons et charges utiles, y compris par identifiant direct et par jeton d'API. |
| **Cloisonnement de la paie** | 4B | Aucune liaison ne peut prendre pour source un objet du domaine Paie hors ordre de virement ; le fichier produit ne contient aucune donnée de rubrique (BNK-5). |
| **Confinement du copilote** | 4A | Aucun outil de déclenchement, de rejeu, d'activation, de lecture de charge utile ou de lecture de secret. |
| **Absence de secret dans les traces** | 4A | Zéro occurrence sur l'ensemble des journaux, charges utiles archivées et messages d'erreur. |
| **Latence de la surface entrante** | 4A | Accusé de réception sous 500 ms au 95e centile, sous charge de rafale simulée. |
| **Non-régression des Phases 1 à 3** | 4A et 4B | Suite complète au vert, connecteurs actifs et connecteurs coupés. |

### 19.3 Métriques de succès

| Métrique | Cible à trois mois | Ce qu'elle révèle si elle décroche |
|---|---|---|
| **Taux d'acceptation au premier envoi, connecteur de conformité** | ≥ 95 % | Un référentiel client incomplet, ou des contrôles préalables insuffisants. Se corrige par les contrôles, pas par le rejeu. |
| **Taux de rapprochement automatique des encaissements** | ≥ 90 % | Des règles de corrélation trop strictes, ou un usage réel du paiement qui contourne le lien produit par WideHalo. |
| **Part des échanges en incident non traités sous 48 h** | ≤ 5 % | Que la console n'est pas consultée. C'est le signal d'alerte du risque P4-R8. |
| **Écart entre coût imputé et facture du tiers** | ≤ 2 % | Une grille mal paramétrée ou une imputation défaillante. Devient un litige commercial si l'écart persiste. |
| **Nombre de ruptures d'interface par connecteur et par an** | ≤ 4 | Que le plafond de douze adaptateurs est trop haut (H28). C'est la métrique qui décidera de la faisabilité d'une Phase 5. |
| **Part des tenants ayant activé au moins un connecteur payant** | ≥ 40 % | Que le modèle économique de la section 15 ne rencontre pas son marché, ou que l'assistant d'enrôlement est trop difficile. |

### 19.4 Conditions de mise en production

- Barrières techniques de la section 19.2 franchies, sans dérogation.
- Scénario « tout coupé » exécuté et concluant — condition non négociable des deux vagues.
- Consentements de sortie configurés et signés par le client pour chaque connecteur activé, avec information sur les catégories de données et les destinataires.
- Plafonds définis pour tous les connecteurs du régime à l'usage, avec destinataire d'alerte renseigné.
- Export de garantie de sortie produit une fois et relu avec le client, avant la première activation d'un connecteur.
- Pour la vague 4A uniquement : validation par un expert-comptable membre de l'ordre du document normalisé produit et de sa correspondance avec la facture, dans les mêmes conditions qu'en Phases 1 et 3.
- Procédure de reprise après indisponibilité prolongée d'un tiers documentée et essayée, pas seulement écrite.

## 20. Annexes

*Glossaire, sources et ce qu'il faut faire avant le sprint 1*

### 20.1 Glossaire — termes propres à la Phase 4

| Terme | Définition telle qu'employée dans ce document |
|---|---|
| **Échange** | Une tentative d'interaction avec un tiers, entrante ou sortante, enregistrée comme une ligne unique du registre. Unité de base de la Phase 4, par analogie avec le mouvement de stock de la Phase 3. |
| **Liaison** | Unité paramétrée par le client : un connecteur, une opération, un type d'objet métier, un sens. C'est l'objet que l'utilisateur active, règle et surveille. |
| **Adaptateur** | Le code propre à un tiers : authentification, protocole, sérialisation, traduction d'erreurs. Ne contient aucune logique métier et ne crée aucune entité. |
| **Opération canonique** | L'un des huit verbes de la section 4.1. Le catalogue en est fermé ; un neuvième verbe signale un besoin qui ne relève pas de ce socle. |
| **Dispositif à contrôle continu** | Modèle réglementaire dans lequel un document commercial est transmis à une autorité et validé par elle avant ou au moment de sa remise au destinataire, par opposition à un contrôle a posteriori sur pièces. |
| **Marquage vérifiable** | Élément apposé sur un document validé permettant à un tiers d'en contrôler l'authenticité auprès de l'autorité — identifiant attribué, code graphique de vérification, sceau. Le vocabulaire précis dépend du dispositif national. |
| **Clé d'idempotence** | Identifiant transmis au tiers permettant de garantir qu'une même opération répétée ne produit qu'un seul effet. Indispensable sur toute opération d'argent. |
| **Clé de corrélation** | Identifiant reliant un échange sortant, la réponse ou la notification qui lui répond, et la pièce métier concernée. Sans elle, aucun rapprochement automatique différé n'est possible. |
| **Disjoncteur** | Mécanisme qui interrompt les appels vers un tiers après une série d'échecs, pour éviter de saturer la file et d'aggraver l'incident. Se referme après une période d'essai. |
| **Consentement de sortie** | Décision explicite, journalisée et révocable, d'activer un connecteur, prise après affichage des catégories de données concernées, du tiers et de son pays d'établissement. |
| **Rapprochement de second niveau** | Association entre un versement groupé reçu d'un agrégateur et le lot d'encaissements individuels qu'il couvre, commission déduite. Étape la plus souvent sous-estimée d'un raccordement de paiement. |
| **Mode d'attente** | État nominal d'un connecteur réglementaire dont le raccordement n'est pas encore ouvert : le document est produit, signé, archivé et mis en file, sans erreur présentée à l'utilisateur. |

### 20.2 Sources de l'analyse de marché

Les ordres de grandeur de la section 3 proviennent des catégories de sources ci-dessous, consultées en septembre 2026. Elles servent à établir des rangs et des ordres de grandeur, pas à être reprises comme chiffres contractuels ; toute reprise dans un document commercial doit être revérifiée à sa date d'usage.

| Domaine | Nature des sources |
|---|---|
| **Suites de productivité** | Communications financières trimestrielles des deux éditeurs concernés ; compilations statistiques sectorielles 2026 mesurant la part de marché selon deux méthodologies distinctes — par nombre de domaines et par sièges payants — dont les résultats divergent et sont tous deux rapportés en section 3.2. |
| **Monnaie électronique mobile** | Rapport annuel de l'association mondiale des opérateurs mobiles sur l'état de l'industrie de la monnaie électronique, édition de mars 2026 portant sur l'exercice 2025 ; rapport annuel de la banque centrale ouest-africaine sur les services financiers numériques ; presse économique africaine spécialisée reprenant ces publications. |
| **Marché malgache du paiement** | Documentation publique des opérateurs et de leur portail développeur ; comparatifs tarifaires locaux vérifiés en 2026 ; publications de la presse et des acteurs numériques malgaches sur la bancarisation, la détention de carte et la pénétration du commerce en ligne. |
| **Facturation électronique** | Analyses d'éditeurs spécialisés dans la conformité fiscale internationale sur le décret malgache du 2 juillet 2025 et sur les dispositifs comparables de la zone francophone ; publications d'éditeurs de logiciels de gestion actifs dans la région ; textes d'application nationaux lorsqu'ils sont publiés. |
| **Messagerie professionnelle** | Documentation et grilles tarifaires du fournisseur ; guides d'intégration régionaux 2026 documentant le passage à une facturation au message au 1er juillet 2025 ; compilations statistiques sur la pénétration du canal en Afrique. |
| **Automatisation et intégration** | Compilations statistiques 2026 sur les trois plateformes dominantes — utilisateurs, clients payants, revenus, nombre d'intégrations ; publications d'analystes sur la convergence des catégories d'intégration et d'automatisation. |
| **Cadre malgache des données personnelles** | Loi n° 2014-038 du 9 janvier 2015 et son décret d'application ; publications de l'association francophone des autorités de protection des données ; point de situation 2026 sur l'activité de l'autorité de contrôle. |

### 20.3 Suites immédiates

| Action | Échéance | Pourquoi elle passe avant le développement |
|---|---|---|
| **Vérifier que les Phases 1 à 3 sont stabilisées, en particulier le moteur de workflow et le compteur de coût** | Avant le sprint 1 | Le hub de flux se greffe sur les transitions de workflow et étend le compteur de coût. Un déclencheur instable produit des échanges parasites, et un échange parasite envoie réellement quelque chose chez un tiers. |
| **Trancher l'arbitrage du support** | Avant le sprint 1 | Question posée en Phase 3 et reportée. La Phase 4 la rend critique : un connecteur en panne est un incident urgent qui survient quand le tiers le décide. Industrialiser, déléguer ou accepter la maintenance — ne pas choisir revient à choisir le troisième. |
| **Arbitrer les rapports ajoutés et la bascule de l'unité de coût de la messagerie** | Sprints 1 à 3 | Le second arbitrage (H26) conditionne la conception du compteur transverse ; le prendre après le sprint 6 signifierait reprendre le socle. |
| **Engager la demande d'habilitation au dispositif de facturation électronique** | Sprint 1 | Le délai n'est pas maîtrisé par l'éditeur (H20, H21) et conditionne la mise en production de la vague 4A. Neuf sprints d'avance sur le besoin, et c'est probablement encore trop peu. |
| **Engager les contrats marchands et la déclaration d'application auprès des acteurs du paiement** | Sprint 11 | Quatre sprints d'avance sur le bloc D. Détermine aussi si l'agrégateur accepte un contrat éditeur (H24), ce qui change le modèle de mise en service de chaque client. |
| **Faire lever H27 par un conseil compétent en protection des données** | Avant le sprint 6 | Le mécanisme de consentement de sortie est conçu au bloc A. Découvrir au sprint 20 qu'une formalité préalable s'impose obligerait à le reprendre alors que six connecteurs l'utiliseront déjà. |
| **Collecter un relevé bancaire réel de chaque banque des clients existants** | Avant le sprint 22 | C'est le seul moyen de lever H25 autrement que par une déclaration. Trois formats découverts au sprint 24 coûtent deux sprints ; trois formats connus au sprint 20 n'en coûtent aucun. |
| **Reprendre les exclusions de la section 2.6 et la matrice 3.9 dans l'offre commerciale** | Avant toute proposition | Télédéclaration, douane, place de marché de connecteurs, éditeur de scénarios : quatre attentes probables du client, quatre risques de litige s'ils ne sont pas écrits (P4-R9). |
| **Établir la liste des tiers sans environnement d'essai** | Sprint 2 | Un tiers sans environnement d'essai coûte environ un sprint supplémentaire et doit être écarté à ce titre, ou son intégration reportée. C'est un critère de sélection, pas un détail d'exécution. |

> Fin du cahier des charges WideHalo v3 — Phase 4. Ce document suppose les Phases 1 à 3 livrées et n'en respécifie aucune décision. Les 54 critères d'acceptation de la section 14 sont écrits pour être traduits en tests, et le plan de la section 16 pour être suivi sprint par sprint. Avec la Phase 4, le produit cesse d'être un système d'enregistrement pour devenir un point de passage : c'est ce qui le rend difficile à remplacer, et c'est aussi ce qui rend l'éditeur responsable de pannes qu'il ne provoque pas. Les deux vont ensemble et ne se séparent pas. Ce qui suivra — localisation OHADA complète, consolidation, ressources humaines élargies — devra se construire par paramétrage des moteurs existants, y compris du moteur de conformité livré ici, qui a été conçu pour cela.
