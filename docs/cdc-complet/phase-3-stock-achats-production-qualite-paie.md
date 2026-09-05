# WideHalo v3 — Cahier des charges Phase 3

*Flux physiques, conformité et personnel de l'ERP WideHalo*

**PHASE 3 — Stock et entrepôt • Achats, import et CREDOC**

*Production • Qualité et HACCP • Paie • Extension Forecast*

| Rubrique | Valeur |
|---|---|
| PROJET | WideHalo — ERP PME |
| DOCUMENT | Cahier des charges |
| VERSION | 3.0 — Phase 3 |
| MAÎTRE D'OUVRAGE | Life MDG |
| PRÉREQUIS | Phases 1 et 2 en production |
| DATE | Septembre 2026 |
| MODE DE DÉVELOPPEMENT | Solo assisté IA (Claude Code) |
| DURÉE PHASE 3 | 38 sprints — deux vagues |
| STATUT | Pour validation |

- **1. Résumé exécutif**
  - Les sept décisions structurantes
  - Périmètre de ce document
- **2. Contexte, objectifs et périmètre**
  - 2.1 Ce dont la Phase 3 hérite
  - 2.2 Objectifs de la Phase 3
  - 2.3 Position dans la trajectoire produit
  - 2.4 Périmètre inclus
  - 2.5 Périmètre exclu
- **3. Utilisateurs cibles et cas d'usage**
  - 3.1 Parcours de référence de la Phase 3
  - 3.2 Ce qui change par rapport aux Phases 1 et 2
- **4. Contraintes du projet**
  - 4.1 Hypothèses ouvertes à lever
- **5. Architecture applicative**
  - 5.1 Couche présentation
  - 5.2 Couche logique métier
  - 5.3 Couche données
  - 5.4 Couche intégration
  - 5.5 Infrastructure
  - 5.6 Couche transverse
- **6. Sécurité**
  - 6.1 Cloisonnement du module Paie
  - 6.2 Intégrité des objets à valeur probante
  - 6.3 Séparation des tâches sur les flux physiques
  - 6.4 Confinement du copilote, étendu
- **7. UX, confort et travail sur le terrain**
  - 7.1 Les contraintes réelles du poste
  - 7.2 Douze composants nouveaux
  - 7.3 Mode dégradé et file de saisie
  - 7.4 Accessibilité et internationalisation
- **8. Gouvernance des données**
  - 8.1 Classification des données ajoutées
  - 8.2 Rétention
  - 8.3 Qualité et contrôles bloquants
  - 8.4 Sauvegarde et reprise
- **9. Interopérabilité et outils tiers**
  - 9.1 Matériel de terrain
  - 9.2 Échanges externes
  - 9.3 Règle de gouvernance des échanges
- **10. Scalabilité**
  - 10.1 Budgets d'architecture révisés
- **11. Choix technologiques**
  - 11.1 Méthode de valorisation du stock
  - 11.2 Calcul des besoins matière
  - 11.3 Moteur de paie
  - 11.4 Briques confirmées sans réexamen
- **12. Socle d'inventaire et modèle de mouvement**
  - 12.1 Le mouvement comme écriture unique
  - 12.2 Unités de mesure et conversions
  - 12.3 Lot, série, emplacement et réservation
  - 12.4 Valorisation et inventaire permanent
  - 12.5 Extension du modèle dimensionnel
- **13. Spécifications fonctionnelles — Phase 3**
  - 13.1 Module Stock et entrepôt
  - 13.2 Module Achats, import et CREDOC
  - 13.3 Module Production
  - 13.4 Module Qualité et HACCP
  - 13.5 Module Paie
  - 13.6 Extension du module Forecast
- **14. Plan de développement — sprints hebdomadaires**
  - 14.1 Ordonnancement et dépendances
  - 14.2 Bloc A — Socle d'inventaire et cadrage (S1 à S7)
  - 14.3 Bloc B — Stock et entrepôt (S8 à S13)
  - 14.4 Bloc C — Achats, import et CREDOC (S14 à S18)
  - 14.5 Bloc D — Production (S19 à S24)
  - 14.6 Bloc E — Qualité et HACCP (S25 à S28)
  - 14.7 Bloc F — Paie (S29 à S33)
  - 14.8 Bloc G — Extension Forecast (S34 à S36)
  - 14.9 Bloc H — Durcissement et mise en production (S37 et S38)
  - 14.10 Répartition du travail humain / assistant
- **15. Estimation détaillée**
  - 15.1 Hypothèses de l'estimation
  - 15.2 Synthèse par bloc
  - 15.3 Comparaison avec les Phases 1 et 2
  - 15.4 Trois scénarios
  - 15.5 Marges appliquées par type de tâche
- **16. Risques et plan de mitigation**
- **17. Critères de recette et métriques de succès**
  - 17.1 Recette fonctionnelle
  - 17.2 Recette technique — barrières bloquantes
  - 17.3 Métriques de succès
  - 17.4 Conditions de mise en production
- **18. Annexes**
  - 18.1 Glossaire — termes propres à la Phase 3
  - 18.2 Documents de référence
  - 18.3 Suites immédiates

## 1. Résumé exécutif

*Ce qu'il faut retenir en une page*

Les Phases 1 et 2 ont couvert ce qui se compte : la vente, l'écriture comptable, l'encaissement, puis la restitution, la prévision et la diffusion. La Phase 3 couvre ce qui se déplace et ce qui se transforme — la matière, le produit, l'heure de travail. C'est la phase qui fait de WideHalo un ERP au sens plein, et c'est aussi la plus exposée : un stock faux se voit le jour même, un bulletin de paie faux se conteste, un lot non tracé peut coûter un marché à l'export.

**Cinq modules qui partagent une seule écriture.** Le mouvement de stock est l'unique enregistrement de variation de quantité du produit : Achats, Production, Qualité, Stock et POS y écrivent tous. Paie est le seul module indépendant du flux physique — il ne s'y raccorde que par l'imputation de la main-d'œuvre au coût de production — et c'est précisément pourquoi il est placé en fin de plan, où un décalage réglementaire ne bloque plus rien.

### Les sept décisions structurantes

1. **Un seul mouvement de stock, une seule vérité de quantité.** Toute variation — réception, transfert, prélèvement, consommation d'atelier, entrée de production, vente, casse, régularisation d'inventaire — est une ligne de la même table, orientée, datée et rattachée à sa pièce d'origine. Aucun module ne tient son propre compteur. La sortie de caisse enregistrée en Phase 1 comme mouvement indicatif devient un mouvement réel : c'est le point d'accroche prévu dès la Phase 1, honoré ici sans reprise du modèle de vente.
2. **Le stock est valorisé en inventaire permanent, en coût unitaire moyen pondéré.** Le CUMP est la seule méthode livrée ; le FIFO par lot en valeur est une option paramétrable dont l'opportunité est arbitrée au sprint 3 ; le LIFO est écarté par principe, le référentiel ne l'admettant pas. L'écriture comptable de variation de stock est produite par le mouvement, et l'écart entre le compte de stock et la valorisation est un contrôle bloquant, pas un rapport que personne ne lit.
3. **Le lot et le numéro de série appartiennent au mouvement, pas à l'article.** C'est ce qui rend la traçabilité amont et aval calculable dans les deux sens et la règle FEFO applicable automatiquement, sans table parallèle à maintenir en cohérence. La généalogie d'un lot n'est pas un document : c'est une requête sur le graphe des mouvements, donc toujours à jour.
4. **La paie est un moteur de règles paramétrées, jamais du code.** Aucun taux, aucun barème, aucun plafond ne figure dans ce document ni ne figurera dans le code. IRSA, CNaPS, OSTIE, FMFP et le plafond adossé au salaire minimum d'embauche sont des paramètres versionnés dans la table livrée en Phase 1, validés par un expert-comptable avant toute mise en production. Une loi de finances change un paramètre, pas une version du logiciel.
5. **Le bulletin publié est immuable, et la correction est une régularisation.** Recalculer silencieusement un bulletin déjà remis est la faute qui détruit la confiance dans un module de paie, parce qu'elle rend impossible d'expliquer un écart au salarié. Une correction produit une régularisation datée, motivée, tracée et visible sur le bulletin suivant.
6. **La production s'arrête au suivi, pas à l'ordonnancement.** Nomenclature, gamme, poste de charge, ordre de fabrication, consommations et déclarations réelles, sous-traitance de façon, rebut, rendement et coût de revient : oui. Ordonnancement à capacité finie, jalonnement automatique, système d'exécution de fabrication temps réel et acquisition depuis les machines : non. Cette limite doit figurer dans l'offre commerciale, pas être découverte en recette.
7. **Forecast tient enfin sa promesse.** L'extension aux besoins matière et à la charge d'atelier, explicitement annoncée comme non livrable en Phase 2, devient un bloc de cette phase. Le modèle dimensionnel construit en Phase 2 doit accueillir les faits de stock, d'achat et de production sans reprise : c'était la condition posée alors, elle est vérifiée au sprint 2 et non supposée.

**Deux vagues plutôt qu'une phase de dix mois.** La Phase 3 est découpée en deux vagues avec une mise en production intermédiaire. La **vague 3A** — socle d'inventaire, Stock et entrepôt, Achats, import et CREDOC — couvre le flux entrant et est mise en production au jalon J2, au sprint 18. La **vague 3B** — Production, Qualité et HACCP, Paie, extension Forecast — suit. Deux raisons : trente-huit sprints sans mise en production est une période pendant laquelle le produit ne gagne rien et le client ne vérifie rien ; et la vague 3A est commercialisable seule auprès d'un négociant ou d'un importateur qui ne transforme pas, ce qui n'est pas le cas de la 3B.

### Périmètre de ce document

Ce document couvre exclusivement la Phase 3. Il suppose les Phases 1 et 2 livrées et stabilisées : socle d'expérience utilisateur, moteur de vues configurables, data grid, chatter, moteur de notification et de canal, référentiel comptable PCG 2005, paramètres réglementaires versionnés, POS, simulation financière, entrepôt analytique en étoile, dictionnaire d'indicateurs, moteur de prévision et gateway IA sont des acquis. Aucune de leurs décisions d'architecture n'est rediscutée ici ; elles sont rappelées uniquement lorsque la Phase 3 s'y raccorde. Ce que la Phase 3 laisse ouvert — localisation OHADA, consolidation multi-sociétés, gestion des ressources humaines au-delà de la paie — relève de la feuille de route produit et non d'une phase déjà cadrée.

## 2. Contexte, objectifs et périmètre

*Ce dont la Phase 3 hérite, et ce qu'elle referme*

### 2.1 Ce dont la Phase 3 hérite

La Phase 3 est la plus lourde des trois en surface fonctionnelle, mais elle n'est tenable que parce qu'elle ne construit presque aucun socle. Huit acquis sont directement réutilisés ; deux d'entre eux — les paramètres versionnés et le mouvement indicatif du POS — ont été livrés en Phase 1 spécifiquement pour cette phase, et leur qualité conditionne son coût.

| Acquis des Phases 1 et 2 | Usage en Phase 3 |
|---|---|
| **Paramètres réglementaires versionnés (core_regulatory_parameter)** | Porte l'intégralité des barèmes, taux, plafonds et tranches de la paie, ainsi que les durées de rétention réglementaires. C'est l'acquis qui rend le bloc Paie court plutôt que structurant : il ne reste qu'à écrire le moteur qui les consomme. |
| **Référentiel comptable abstrait (PCG 2005)** | Les écritures d'inventaire permanent, de variation de stock, de production immobilisée et de paie s'y branchent sans logique comptable nouvelle. L'abstraction absorbera aussi la variante OHADA le jour venu. |
| **Mouvement de sortie POS indicatif** | Point d'accroche prévu dès la Phase 1 : le POS devient producteur de mouvements réels par simple bascule de nature, sans reprise du modèle de vente ni des tickets historiques. |
| **Moteur de vues, data grid, chatter, workflow** | Les écrans de stock, d'atelier, de qualité et de paie sont majoritairement construits par configuration. Douze composants nouveaux seulement, tous orientés terrain (scan, tablette, arborescence). |
| **Protocole hors ligne du POS** | Réutilisé pour l'entrepôt et l'atelier : file de saisie locale, numérotation préfixée, réconciliation sans doublon. Le protocole le plus difficile de la Phase 1 sert trois fois (H19). |
| **Entrepôt en étoile et dictionnaire d'indicateurs** | Accueille les faits de mouvement, de réception et d'ordre de fabrication. Rotation, couverture, taux de service, rendement et coût de revient deviennent des indicateurs gouvernés, pas des calculs d'écran. |
| **Moteur de prévision** | Étendu aux besoins matière et à la charge d'atelier : la mécanique de série, de rétrotest et d'erreur publiée existe déjà, seule la maille et la source changent. |
| **Canal de messagerie et moteur de notification** | Accusé de commande fournisseur, alerte de péremption, notification de rappel produit, mise à disposition du bulletin. Canal de confort ; aucun processus de la Phase 3 n'en dépend. |

### 2.2 Objectifs de la Phase 3

| Objectif | Énoncé | Comment il est mesuré |
|---|---|---|
| **O1 — Vérité du stock** | Que la quantité affichée soit la quantité physique, et qu'un écart soit mesuré et expliqué plutôt que découvert à l'inventaire annuel. | Écart d'inventaire tournant sous le seuil défini par famille ; zéro mouvement rendant un stock négatif sans dérogation tracée ; rapprochement stock / comptabilité à l'ariary près. |
| **O2 — Coût de revient réel** | Que le prix de revient intègre le coût débarqué pour un article importé, et la matière et la main-d'œuvre réellement consommées pour un article fabriqué. | Coût débarqué ventilé sur 100 % des réceptions d'import ; écart entre coût réel et coût prévu publié pour chaque ordre de fabrication clôturé. |
| **O3 — Traçabilité opposable** | Qu'un lot suspect permette d'identifier l'amont et l'aval en quelques secondes, avec une trace qui puisse être produite devant un client ou un auditeur. | Généalogie amont et aval restituée en moins de 5 secondes ; exercice de rappel blanc réussi avant mise en production ; journal horodaté non modifiable. |
| **O4 — Paie juste et paramétrée** | Qu'un bulletin soit exact, explicable ligne à ligne au salarié, et qu'un changement de barème n'exige aucune livraison logicielle. | Validation écrite d'un expert-comptable OECFM sur un jeu de bulletins témoins couvrant les cas limites ; test d'intégration continue détectant tout taux ou plafond écrit en dur. |
| **O5 — Autonomie du terrain** | Qu'un magasinier ou un chef d'atelier travaille au scan sur tablette, y compris quand le réseau tombe, sans repasser par un tableur ou un cahier. | Parcours UC15 à UC19 réalisables intégralement en mode dégradé ; facilité perçue (SEQ) ≥ 6 sur les écrans terrain ; zéro perte de saisie en test de coupure. |
| **O6 — Prévision complète** | Que la promesse ouverte en Phase 2 soit tenue : prévoir la matière à commander et la charge d'atelier, et non seulement les ventes. | Proposition de réapprovisionnement générée, acceptée ou rejetée avec motif ; charge d'atelier projetée comparée au réalisé et son erreur publiée, comme pour les ventes. |

### 2.3 Position dans la trajectoire produit

| Phase | Modules | Rôle | Statut |
|---|---|---|---|
| **Phase 1** | Socle UX, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, Patronnage, IA | Rendre le produit utilisable et conforme. | Prérequis — en production |
| **Phase 2** | Business Intelligence, Forecast, Strategy, WhatsApp | Rendre le produit pilotable et communicant. | Prérequis — en production |
| **Phase 3 vague 3A** | Socle d'inventaire, Stock et entrepôt, Achats, import et CREDOC | Maîtriser le flux entrant et la vérité physique du stock. Commercialisable seule auprès d'un négociant ou d'un importateur. | Objet de ce document |
| **Phase 3 vague 3B** | Production, Qualité et HACCP, Paie, extension Forecast | Couvrir la transformation, la conformité et le personnel. Referme la couverture ERP des deux verticales. | Objet de ce document |
| **Après la Phase 3** | Localisation OHADA / SYSCOHADA, consolidation multi-sociétés, gestion des ressources humaines élargie, maintenance des équipements | Extension géographique et approfondissement. Aucune n'est cadrée à ce jour. | Feuille de route — non chiffré |

### 2.4 Périmètre inclus

- **Socle d'inventaire** : extension de l'article (stockable, service, nomenclaturé, gestion par lot ou par numéro de série), unités de mesure et conversions, dépôts, zones et emplacements, mouvement de stock unique et orienté, réservation, valorisation en CUMP, interface d'inventaire permanent avec la comptabilité, bascule du mouvement indicatif du POS en mouvement réel.
- **Module Stock et entrepôt** : réception au scan, transfert entre emplacements et entre dépôts, préparation et expédition, règle de prélèvement FEFO puis FIFO, inventaire tournant et inventaire complet, écarts avec validation par seuil, règles de réapprovisionnement (point de commande, stock de sécurité, quantité de réapprovisionnement), étiquetage et codes-barres, écran magasinier tablette, mode dégradé avec file de saisie.
- **Module Achats, import et CREDOC** : demande d'achat et circuit d'approbation, consultation fournisseur et comparatif, commande d'achat, réception partielle et retour fournisseur, facture fournisseur et rapprochement à trois voies, dossier d'import, cycle de vie du crédit documentaire, liasse documentaire, référence de déclaration en douane et droits liquidés, coûts annexes, ventilation du coût débarqué par référence, exposition au change Ariary.
- **Module Production** : nomenclature de fabrication et nomenclature de process avec sous-produits et rendement, consommation matière dépendante de la taille pour la verticale textile, gamme, opérations et postes de charge, ordre de fabrication, kanban d'atelier, déclaration de consommation et de production, rebut et motif, sous-traitance de façon, généalogie de lot, coût de revient de fabrication, taux de conformité au premier passage.
- **Module Qualité et HACCP** : plan de contrôle, points de contrôle critiques et limites critiques, prélèvement et enregistrement de mesure, blocage et libération de lot, non-conformité et action corrective, certificat d'analyse fournisseur, procédure de rappel avec traçabilité aval, journal horodaté à valeur probante.
- **Module Paie** : dossier salarié, contrat et avenants, éléments fixes et variables, absences et congés, pointage et heures supplémentaires, moteur de rubriques et de règles adossé aux paramètres versionnés, cycle de paie et contrôles de cohérence, bulletin, journal de paie et écritures comptables, déclarations sociales et fiscales, prêts et acomptes, coût du personnel par centre de charge et imputation de la main-d'œuvre au coût de production.
- **Extension du module Forecast** : besoins matière dérivés de la prévision de ventes et des nomenclatures, proposition de réapprovisionnement soumise à décision humaine, charge d'atelier projetée par poste, alertes de couverture et de péremption.
- **Transverse** : douze composants d'interface nouveaux, mode dégradé étendu à l'entrepôt et à l'atelier, extension du modèle dimensionnel de la Phase 2, budgets d'architecture révisés, nouveau budget de rubriques de paie.

### 2.5 Périmètre exclu

Un périmètre sans exclusions explicites dérive. Les points suivants sont volontairement hors Phase 3, et doivent être repris tels quels dans l'offre commerciale.

- **Ordonnancement à capacité finie**, jalonnement automatique, système d'exécution de fabrication temps réel et acquisition automatique de données depuis les machines. La Phase 3 constate la production, elle ne la planifie pas à la minute.
- **Gestion d'entrepôt avancée** : optimisation du chemin de prélèvement, préparation par vagues, cross-docking, gestion de contenants et de supports. Les emplacements et le FEFO sont livrés ; l'optimisation ne l'est pas.
- **Transport, tournées de livraison et suivi de flotte.**
- **Maintenance des équipements**, bien qu'elle soit le prolongement naturel du poste de charge.
- **Interface machine avec la banque pour le crédit documentaire et avec le système douanier.** Le dossier d'import est tenu dans WideHalo ; les échanges avec la banque et l'administration restent documentaires (H14, H15).
- **Exécution du paiement des salaires.** Le module produit un ordre de virement exportable et un état de paiement ; il ne transmet rien à une banque ni à un opérateur de monnaie électronique.
- **Gestion des ressources humaines au-delà de la paie** : recrutement, entretiens annuels, formation, gestion des compétences, organigramme dynamique.
- **Multi-devise généralisée.** Les achats à l'import sont saisis en devise et convertis à une date de référence ; la comptabilité, le stock et la paie restent tenus en Ariary.
- **Localisation OHADA / SYSCOHADA et consolidation multi-sociétés**, exclues depuis la Phase 1 et toujours hors périmètre.
- **Apprentissage automatique sur la prévision de besoins** : même principe qu'en Phase 2, méthodes interprétables uniquement. Une proposition de commande que l'acheteur ne peut pas expliquer ne sera pas suivie.

**Trois reprises que la Phase 3 impose dans l'existant, et qui ne sont pas du développement.** Premièrement, la sortie de caisse passe d'indicatif à réel : tout écart accumulé depuis la mise en production de la Phase 1 devient visible d'un coup. Deuxièmement, chaque article doit recevoir ses attributs de gestion — unité de stock, méthode de valorisation, gestion par lot ou par série, seuils de réapprovisionnement — avant activation, article par article. Troisièmement, le stock initial doit être établi par un inventaire physique daté : sans lui, la valorisation démarre fausse et le reste, car le CUMP se traîne indéfiniment. Ces trois travaux relèvent du client, avec un accompagnement à chiffrer séparément du développement. Les inscrire dans le contrat évite qu'ils ne soient découverts au sprint 7, quand le socle sera prêt et les données ne le seront pas.

## 3. Utilisateurs cibles et cas d'usage

*Le retour des utilisateurs intensifs, cette fois debout*

La Phase 2 servait des décideurs assis, peu nombreux, qui consultaient. La Phase 3 sert des opérateurs debout, souvent gantés, dans un entrepôt mal couvert par le réseau ou dans un atelier bruyant, qui saisissent des dizaines de fois par jour. C'est un changement d'exigence plus profond qu'un changement de fonctionnalités : un écran qui demande deux mains et une bonne connexion ne sera pas utilisé, la saisie repartira sur un cahier, et le stock redeviendra faux en trois semaines.

| Persona | Contexte d'usage réel | Attentes prioritaires | Écrans concernés |
|---|---|---|---|
| **Magasinier et cariste** **Nouvel utilisateur intensif** | Debout, en mouvement, tablette ou terminal à la main, gants fréquents. Réseau intermittent au fond de l'entrepôt. Cadence élevée, tolérance nulle à l'attente. | Scanner plutôt que saisir ; savoir immédiatement où poser et où prendre ; continuer à travailler quand le réseau tombe et ne rien perdre. | Réception, transfert, préparation, inventaire tournant, consultation de stock. |
| **Chef d'atelier** | Suit dix à trente ordres en parallèle, arbitre les priorités dans la journée, constate les rebuts et les retards. | Voir l'avancement d'un coup d'œil, déclarer une production en trois gestes, comprendre pourquoi un rendement décroche. | Kanban d'atelier, ordre de fabrication, déclarations, rendement. |
| **Acheteur et importateur** | Assis, dossiers longs (six semaines à six mois), nombreuses pièces jointes, échanges avec banque et transitaire hors de l'outil. | Un dossier qui rassemble tout, un statut qui dit où en est le crédit documentaire, et un coût débarqué calculé plutôt que reconstitué au tableur. | Demande d'achat, commande, dossier d'import, CREDOC, coût débarqué. |
| **Contrôleur qualité** | Alterne poste fixe et prélèvements en atelier. Responsable personnellement des décisions de libération. | Enregistrer une mesure sans ambiguïté, bloquer un lot en un geste, et pouvoir prouver plus tard ce qui a été décidé et quand. | Plan de contrôle, prélèvements, blocage et libération, non-conformités, rappel. |
| **Gestionnaire de paie** **Nouvel utilisateur** | Cycle mensuel dense et sous contrainte de date. Travaille aujourd'hui au tableur, avec des reprises manuelles et une relecture ligne à ligne. | Un cycle qui contrôle avant de publier, un bulletin explicable au salarié, et un barème modifiable sans appeler l'éditeur. | Dossier salarié, variables de paie, cycle, contrôles, bulletins, déclarations. |
| **Comptable** | Garant de la cohérence, comme en Phase 2. Sera le premier à voir un compte de stock qui ne suit pas la valorisation. | Que l'inventaire permanent produise des écritures justes et rapprochables, et que la paie se déverse sans ressaisie. | Rapprochement stock, journal de paie, écritures de production. |
| **Dirigeant PME** | Consulte, arbitre, signe. Intéressé par la couverture, la marge réelle et le coût du personnel plus que par le détail des mouvements. | Savoir ce qu'il a en stock, ce que ça vaut, ce que ça coûte de le fabriquer, et ce qu'il devra commander. | Tableau de bord, couverture, coût de revient, proposition de réapprovisionnement. |
| **Salarié** **Destinataire, non-utilisateur** | Reçoit un bulletin, conteste parfois une ligne. Peut n'avoir accès qu'à un téléphone d'entrée de gamme. | Un bulletin lisible et un interlocuteur capable d'expliquer chaque ligne. | Bulletin, mise à disposition par le canal. |

### 3.1 Parcours de référence de la Phase 3

La numérotation prolonge celle des Phases 1 et 2 (UC1 à UC14). Ces dix parcours servent de tâches de référence pour les mesures de la section 17, et leur ligne de base est établie au sprint 1 sur la pratique actuelle.

| Réf. | Parcours | Ce qu'il éprouve réellement |
|---|---|---|
| **UC15** | Réceptionner une livraison au scan, avec numéro de lot et date limite | Le confort de saisie terrain et la robustesse du mode dégradé. |
| **UC16** | Préparer une commande en FEFO et expédier | La justesse de la règle de prélèvement et la réservation. |
| **UC17** | Réaliser un inventaire tournant et justifier un écart | La séparation des tâches et le contrôle par seuil. |
| **UC18** | Ouvrir un dossier d'import et le suivre jusqu'au coût débarqué | Le cycle de vie du CREDOC et la ventilation des coûts annexes. |
| **UC19** | Lancer un ordre de fabrication et déclarer une production d'atelier | La nomenclature, la consommation réelle et le kanban tablette. |
| **UC20** | Contrôler un point critique, puis libérer ou bloquer un lot | L'ergonomie du contrôle et l'opposabilité de la décision. |
| **UC21** | Déclencher un rappel produit et lister l'aval impacté | La performance et l'exactitude de la généalogie. |
| **UC22** | Préparer, contrôler et publier un cycle de paie mensuel | Le moteur de rubriques, les contrôles de cohérence et le verrouillage. |
| **UC23** | Corriger une erreur de paie après publication | L'immutabilité du bulletin et le mécanisme de régularisation. |
| **UC24** | Générer une proposition de réapprovisionnement depuis la prévision | L'articulation Forecast — nomenclature — stock, et l'explicabilité. |

### 3.2 Ce qui change par rapport aux Phases 1 et 2

| Dimension | Phases 1 et 2 | Phase 3 |
|---|---|---|
| **Nature de l'utilisateur** | Assis, un écran, une souris. | Debout, une main, un scanner. Le confort tactile devient une exigence fonctionnelle, pas un raffinement. |
| **Conséquence d'une erreur** | Un chiffre faux à corriger. | Une quantité physique fausse, un lot livré à tort, un salaire contesté. La correction a un coût hors du logiciel. |
| **Rapport au réseau** | Le POS était la seule exception hors ligne. | L'entrepôt et l'atelier deviennent des zones de mode dégradé par défaut ; le protocole du POS y est réutilisé (H19). |
| **Rapport à la preuve** | Le journal d'audit sert au diagnostic. | Le journal devient une pièce opposable : décision de libération, généalogie, bulletin. Il change de statut, donc d'exigences. |
| **Rapport au réglementaire** | Comptabilité et fiscalité, validées une fois. | Paie et sécurité alimentaire, qui évoluent et qui engagent l'entreprise cliente vis-à-vis de tiers. |

## 4. Contraintes du projet

*Ce qui est imposé et non négociable*

| Catégorie | Contrainte | Conséquence sur la conception |
|---|---|---|
| **Prérequis** | Les Phases 1 et 2 doivent être en production et stabilisées. Le modèle dimensionnel de la Phase 2 doit accueillir de nouveaux faits sans reprise. | Vérification au sprint 2 plutôt que supposition. Si le modèle dimensionnel doit être repris, le bloc G est replanifié avant d'engager le bloc B. |
| **Organisationnelle** | Toujours un seul développeur, qui assure désormais le support de deux phases en production. | La capacité retenue passe de 4,5 à **4 jours effectifs par semaine**. C'est la contrainte qui explique le découpage en deux vagues et la longueur de la phase. |
| **Technique imposée** | Même pile, même instance PostgreSQL, même bibliothèque de composants. Aucun composant d'infrastructure nouveau. | Le moteur de règles de paie est écrit dans l'application ; le calcul de besoins est fait en base. Ni moteur de règles tiers, ni solveur externe (section 11). |
| **Terrain** | Parc hétérogène de tablettes d'entrée de gamme, scanners du marché local, imprimantes d'étiquettes ; réseau intermittent en entrepôt et en atelier. | Mode dégradé obligatoire avec file de saisie locale et réconciliation, sur le protocole éprouvé du POS. Aucun pilote propriétaire : le scanner est vu comme un clavier. |
| **Réglementaire — paie** | Droit du travail malgache, IRSA, CNaPS, OSTIE, FMFP, plafond de cotisations adossé au salaire minimum d'embauche. | Aucun barème en dur, aucun taux dans ce document. Validation par un expert-comptable OECFM obligatoire ; un paramètre non validé reste marqué comme tel et l'écran l'affiche. |
| **Réglementaire — traçabilité** | Principes HACCP et exigences de traçabilité amont / aval des marchés d'exportation agroalimentaires. | Journal horodaté non modifiable, généalogie reconstituable dans les deux sens, exercice de rappel blanc en recette avant mise en production de la vague 3B. |
| **Données personnelles** | La paie introduit des données personnelles sensibles : rémunération, situation familiale, absences pour raison de santé, identifiants d'organismes sociaux. | Cloisonnement du module, second facteur obligatoire, restriction d'affichage, rétention légale distincte de la rétention commerciale, registre des traitements étendu. |
| **Comptable** | Inventaire permanent : toute variation de stock produit ou prépare une écriture. | Le rapprochement entre le compte de stock et la valorisation est un contrôle bloquant au rafraîchissement et à la clôture, pas un état informatif. |
| **Produit** | Budgets d'architecture toujours vérifiés en intégration continue. | Rehaussés en section 10, jamais contournés. Un budget de rubriques de paie est introduit, sur le modèle du budget de rapports de la Phase 2. |
| **Délai** | 38 sprints hebdomadaires, avec une mise en production intermédiaire au sprint 18. | L'ordre des blocs suit la dépendance physique, pas la valeur perçue. Le bloc Paie, seul module indépendant, est le seul déplaçable. |

### 4.1 Hypothèses ouvertes à lever

La numérotation prolonge celle des Phases 1 et 2 (H1 à H11). Chaque hypothèse a un sprint de levée assigné ; une hypothèse non levée à la date prévue devient un risque actif et remonte en revue de sprint.

| Réf. | Hypothèse posée | Levée prévue |
|---|---|---|
| **H12** | La sortie de caisse enregistrée en Phase 1 comme mouvement indicatif est exploitable telle quelle comme mouvement réel, sans reprise du modèle de vente ni des tickets historiques. | Sprint 2 — vérification sur les données de production, sur un tenant réel et non sur un jeu de test. |
| **H13** | Le coût unitaire moyen pondéré suffit à tous les clients visés ; aucun ne réclame un FIFO par lot en valeur, ni un coût standard avec écarts. | Sprint 3 — entretien client. L'arbitrage conditionne la conception de la couche de valorisation, il ne peut pas être différé. |
| **H14** | Les banques locales n'exposent aucune interface exploitable pour le crédit documentaire ; les échanges restent documentaires et le suivi de statut est saisi manuellement. | Sprint 12 — vérification auprès d'au moins deux banques de la place. |
| **H15** | La déclaration en douane reste établie et déposée hors de WideHalo. Le produit se limite à porter la référence de déclaration, les droits et taxes liquidés et les documents. Le périmètre d'interface éventuel du système douanier et du guichet unique du commerce extérieur n'est pas vérifié à la rédaction et n'est pas décrit ici. | Sprint 14 — vérification auprès d'un transitaire et, si nécessaire, de l'administration. Ne peut pas être levée par défaut. |
| **H16** | Les nomenclatures existantes chez les clients pilotes sont suffisamment complètes et fiables pour alimenter un calcul de besoins. À défaut, leur saisie est un travail de mise en service à la charge du client. | Sprint 19 — diagnostic sur données réelles, avant l'engagement du bloc D. |
| **H17** | Les barèmes en vigueur, les conventions applicables et les usages de l'entreprise — primes, indemnités, mode de décompte des heures, traitement des absences — sont obtenables du client et validables par un expert-comptable dans le calendrier prévu. | Sprints 25 à 29 — recueil puis validation. C'est l'hypothèse la plus lourde de la phase et la seule qui ne peut être ni déléguée à l'assistant ni tranchée par l'éditeur. |
| **H18** | Les déclarations sociales et fiscales attendues par les organismes sont des formulaires ou des fichiers reproductibles depuis WideHalo, sans interface machine ni format propriétaire imposé. | Sprint 31 — vérification des formats réellement exigés au moment du développement. |
| **H19** | Le protocole de réconciliation hors ligne du POS est réutilisable tel quel pour l'entrepôt et l'atelier, dont les saisies sont moins nombreuses mais plus longues et plus souvent interrompues. | Sprint 8 — banc d'essai de coupure et de reprise sur un parcours de réception complet. |

**Règle de gestion des hypothèses, inchangée depuis la Phase 1.** Une hypothèse non levée à sa date devient un risque actif et remonte en revue de sprint. Deux hypothèses de cette phase ne peuvent en aucun cas être « levées par défaut » au motif que le développement doit avancer : **H17**, parce qu'un barème supposé produit un bulletin faux, et un bulletin faux est un contentieux ; et **H15**, parce qu'une obligation déclarative inventée expose le client. Dans les deux cas, le paramètre reste marqué non validé en base et l'écran affiche cet état à l'utilisateur.

## 5. Architecture applicative

*Aucune couche nouvelle, deux moteurs nouveaux*

L'architecture de la Phase 3 n'introduit ni service ni composant d'infrastructure. Le monolithe modulaire Django reste le seul processus applicatif, le gateway IA reste le seul service séparé, et l'instance PostgreSQL reste unique. Ce qui change tient en deux moteurs internes : le **moteur de mouvement et de valorisation** et le **moteur de règles de paie**. Ce sont des moteurs, non du code métier répété — la même logique qui a produit le moteur de vues en Phase 1 et la couche sémantique en Phase 2. C'est la seule manière connue de tenir cinq modules supplémentaires avec un développeur.

****Architecture cible — Phase 3****

```
NAVIGATEUR (bureau · tablette atelier · terminal entrepôt)
   │  HTML + fragments HTMX · Alpine.js · service worker (file de saisie)
   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ CADDY — TLS, compression, en-têtes de sécurité                       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 1. PRÉSENTATION                            [ socle Phase 1 ]     │ │
│ │   shell · launchpad · data grid · vues configurables · chatter   │ │
│ │   + 12 composants terrain : scan · lot · emplacement ·           │ │
│ │     nomenclature · atelier · contrôle · rappel · bulletin ·      │ │
│ │     pointage · coût débarqué                                     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 2. LOGIQUE MÉTIER (Django, monolithe modulaire)                  │ │
│ │   Stock/Entrepôt  Achats/Import  Production  Qualité      PAIE   │ │
│ │        └───────────────┴────────────┴──────────┘           │     │ │
│ │                        ▼                                   ▼     │ │
│ │   ┌─────────────────────────────┐  ┌──────────────────────────┐  │ │
│ │   │ MOTEUR DE MOUVEMENT         │  │ MOTEUR DE RÈGLES DE PAIE │  │ │
│ │   │ orientation · réservation · │  │ rubriques ordonnées ·    │  │ │
│ │   │ FEFO/FIFO · lot & série ·   │  │ bases · dépendances ·    │  │ │
│ │   │ valorisation CUMP           │  │ cumuls · régularisation  │  │ │
│ │   └─────────────────────────────┘  └──────────────────────────┘  │ │
│ │   moteurs Phase 1/2 : workflow · notifications · audit ·         │ │
│ │   référentiel comptable abstrait · paramètres versionnés         │ │
│ │   └── POS (Phase 1) : la sortie de caisse devient réelle         │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 3. DONNÉES — PostgreSQL · RLS · mouvement partitionné/exercice   │ │
│ │   opérationnel ──rafraîchissement──> entrepôt en étoile (Ph. 2)  │ │
│ │                    + faits mouvement / OF / réception / paie     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│   ▲ API django-ninja — LECTURE SEULE (aucun outil sur la paie)       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 4. INTÉGRATION  widehalo-ai-gateway · canal de messagerie ·      │ │
│ │   imprimante d'étiquettes · exports douane/banque/organismes     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
  5. INFRASTRUCTURE : inchangée — Hetzner · Coolify · Docker · Caddy
  6. TRANSVERSE : sécurité · gouvernance · i18n · audit à valeur probante
```

### 5.1 Couche présentation

Aucune refonte : la bibliothèque de la Phase 1 et le moteur de vues couvrent la majorité des écrans par configuration. Douze composants sont ajoutés, tous justifiés par une contrainte de terrain que le socle ne couvre pas : saisie au scan, sélection de lot avec date limite, plan d'emplacements, arborescence de nomenclature, tableau d'atelier, liste de contrôle qualité, arbre de rappel, visualiseur de bulletin, grille de pointage, ventilation de coût débarqué, convertisseur d'unité et champ quantité à double unité. Ils sont détaillés en section 7.2. Le mode dégradé, jusqu'ici réservé au POS, est étendu aux écrans de réception, de transfert, d'inventaire et de déclaration d'atelier.

### 5.2 Couche logique métier

Cinq modules nouveaux, mais quatre moteurs seulement. C'est le rapport qu'il faut maintenir : la surface fonctionnelle croît, le nombre de mécanismes à comprendre ne doit pas croître au même rythme.

| Moteur | Responsabilité | Pourquoi c'est un moteur et non du code de module |
|---|---|---|
| **Moteur de mouvement** | Valider, orienter, dater et journaliser toute variation de quantité ; appliquer la réservation, la règle de prélèvement FEFO puis FIFO, l'interdiction de stock négatif et la traçabilité lot / série. | Cinq modules produisent des mouvements. Si chacun écrivait sa propre logique, il y aurait cinq façons différentes de rendre le stock faux. |
| **Moteur de valorisation** | Calculer et maintenir le coût unitaire moyen pondéré, produire ou préparer l'écriture d'inventaire permanent, exposer la valeur de stock à toute date. | La valorisation est la jonction entre le physique et le comptable. Elle doit être unique, testable indépendamment, et rejouable sur un historique. |
| **Moteur de nomenclature et de besoins** | Développer une nomenclature à plusieurs niveaux, calculer une consommation théorique, confronter besoin brut, stock disponible et en-cours pour proposer un réapprovisionnement. | Utilisé par la Production (consommation prévue), par Forecast (besoin matière) et par le coût de revient prévisionnel. |
| **Moteur de règles de paie** | Évaluer des rubriques ordonnées avec leurs bases, leurs dépendances, leurs conditions d'application et leurs cumuls, à partir de paramètres versionnés à la date du bulletin. | Un barème change au moins une fois par an. Un moteur transforme ce changement en modification de paramètre ; du code le transforme en livraison, en test de non-régression et en risque. |

La traçabilité n'a pas de moteur dédié : elle est une lecture du graphe des mouvements. C'est un choix délibéré — une table de généalogie entretenue en parallèle diverge tôt ou tard du mouvement réel, et la divergence n'est découverte que le jour du rappel.

### 5.3 Couche données

- **Mouvement de stock** : table centrale, partitionnée par exercice dès la conception, indexée sur tenant, article, emplacement, lot et date. C'est la table qui croîtra le plus vite du produit, POS compris.
- **Aucune quantité dénormalisée qui ne soit reconstructible.** Le stock par article et par emplacement est un agrégat matérialisé, rafraîchi par le moteur et vérifiable par recalcul complet. Un contrôle nocturne compare l'agrégat au recalcul et alerte sur divergence.
- **Row Level Security** étendue à toutes les tables nouvelles, y compris les tables de paie et les faits analytiques associés, sur le modèle inchangé de la Phase 1.
- **Contraintes en base** plutôt qu'en application là où c'est possible : unicité du couple lot / article, cohérence d'orientation du mouvement, interdiction d'une quantité nulle, immutabilité du bulletin publié.
- **Extension du modèle dimensionnel** de la Phase 2 par de nouveaux faits, sans modification des dimensions conformes existantes. Voir 12.5.

### 5.4 Couche intégration

Trois raccordements matériels et quatre échanges documentaires, tous détaillés en section 9. Le principe est constant depuis la Phase 1 : aucun pilote propriétaire, aucun composant à installer sur le poste. Le scanner est vu comme un clavier, l'imprimante d'étiquettes reçoit un flux d'impression standard, et les échanges avec la banque, la douane et les organismes sociaux sont des documents et des fichiers produits par WideHalo, jamais des appels machine.

Le gateway IA gagne des outils de lecture sur le stock, les ordres de fabrication et les dossiers d'import. Il n'en gagne aucun sur la paie : ni consultation, ni résumé, ni aide à la rédaction. C'est une exclusion de principe, pas une précaution temporaire, et elle est vérifiée en intégration continue.

### 5.5 Infrastructure

Inchangée. Les deux files de worker introduites en Phase 2 suffisent : le calcul de besoins et le recalcul de valorisation rejoignent la file longue, aux côtés du rafraîchissement de l'entrepôt, tandis que la file courte reste réservée aux tâches interactives. Trois ajouts d'exploitation seulement : une fenêtre planifiée pour le calcul de besoins, la surveillance de la profondeur de la file de réconciliation terrain — l'indicateur qui dira si le mode dégradé fonctionne réellement —, et une alerte sur la durée du contrôle de cohérence nocturne entre agrégat et recalcul.

### 5.6 Couche transverse

Sécurité (section 6) et gouvernance des données (section 8) traversent toutes les couches et ne sont pas des sous-parties de l'infrastructure. La Phase 3 y ajoute un changement de statut du journal d'audit : il cesse d'être un outil de diagnostic pour devenir une pièce opposable. Une décision de libération de lot, une généalogie produite lors d'un rappel et un bulletin publié doivent pouvoir être produits devant un client, un auditeur ou un salarié. Cela impose des exigences d'intégrité que la section 6.2 détaille.

**Pas de moteur de règles tiers pour la paie, pas de solveur externe pour les besoins.** Les deux tentations sont réelles et les deux sont écartées pour la même raison : elles ajoutent un composant à exploiter, un langage à maîtriser et une frontière où la donnée se désynchronise, au bénéfice d'une puissance dont le volume visé n'a pas l'usage. Une PME de cinquante salariés n'a pas besoin d'un moteur de règles industriel ; elle a besoin que son barème soit modifiable sans appeler l'éditeur, ce qu'une table de rubriques paramétrées suffit à garantir. Le raisonnement complet et les alternatives figurent en section 11.

## 6. Sécurité

*Deux natures de données nouvelles : la rémunération et la preuve*

Les Phases 1 et 2 protégeaient des données comptables et commerciales de tiers. La Phase 3 ajoute deux natures nouvelles, qui appellent chacune une réponse propre. La rémunération est une donnée personnelle sensible dont la divulgation interne fait un dégât social immédiat et irréversible. La preuve — décision de libération, généalogie de lot, bulletin publié — est une donnée dont la valeur tient à son intégrité : une trace modifiable ne prouve rien. Les priorités de la Phase 1 restent valables et ne sont pas rediscutées : isolation entre clients, traçabilité des écritures, confinement du copilote.

### 6.1 Cloisonnement du module Paie

- **Rôle dédié, jamais implicite.** L'accès à la paie relève d'un rôle propre, qui n'est inclus ni dans le rôle Administrateur fonctionnel, ni dans le rôle Comptable, ni dans le rôle Dirigeant par défaut. Le dirigeant peut se l'attribuer ; il doit le faire explicitement, et l'attribution est auditée.
- **Second facteur obligatoire** pour tout rôle donnant accès à un montant de rémunération individuel, sans exception ni dérogation par paramètre.
- **Restriction d'affichage par défaut.** Les montants individuels sont masqués dans les listes et révélés à la demande, l'action de révélation étant journalisée. L'objectif est de rendre impossible la lecture d'un salaire par-dessus l'épaule, qui est le mode de fuite réel dans une PME.
- **Aucun export libre.** L'export d'un journal de paie ou d'une liste de rémunérations est une action distincte, soumise à droit et journalisée avec son périmètre. Un export ne peut pas être planifié ni diffusé par le canal de messagerie.
- **Aucun outil IA sur le périmètre paie**, y compris en lecture et y compris agrégé. Vérifié par un test d'intégration continue qui échoue si un outil déclaré touche une table de paie.
- **Le salarié n'a pas de compte.** Il n'existe pas de portail salarié en Phase 3 : le bulletin est remis par le gestionnaire, éventuellement par le canal de messagerie avec consentement. Un portail multiplierait les comptes à gérer pour un bénéfice faible à cette taille d'entreprise.

### 6.2 Intégrité des objets à valeur probante

| Objet | Exigence d'intégrité | Mise en œuvre |
|---|---|---|
| **Bulletin publié** | Immuable. Aucune voie applicative, y compris l'API et y compris pour un administrateur, ne permet de le modifier ou de le supprimer. | Contrainte en base et contrôle applicatif ; toute correction passe par une régularisation datée sur un cycle ultérieur (PAY-9). |
| **Décision de libération ou de blocage de lot** | Horodatée, nominative, motivée, non rétroactive. Une libération ne peut pas être antidatée. | Écriture au journal d'audit avec identité, horodatage serveur, motif obligatoire ; l'état du lot est dérivé de la dernière décision, jamais saisi directement. |
| **Généalogie de lot** | Reconstituable à l'identique plus tard, y compris après archivage des exercices anciens. | Calculée depuis les mouvements, jamais entretenue en parallèle ; le mouvement n'est jamais supprimé, une annulation est un mouvement inverse. |
| **Écart d'inventaire validé** | Non modifiable après validation ; la régularisation est un mouvement, pas une correction de saisie. | Verrouillage à la validation ; le mouvement de régularisation porte la référence de la session d'inventaire. |
| **Journal de rappel** | Séquence d'événements horodatés, non réordonnable, exportable en un document daté. | Journal en ajout seul ; export figé avec la date et l'identité du déclencheur. |

**Un mouvement de stock ne se supprime jamais, et un bulletin publié ne se recalcule jamais.** Ce sont les deux règles dont dépend tout le reste. Un mouvement supprimé rend la généalogie fausse sans que rien ne le signale, et l'erreur n'apparaît que le jour du rappel — c'est-à-dire le seul jour où elle est inacceptable. Un bulletin recalculé silencieusement rend impossible d'expliquer au salarié l'écart entre ce qu'il a reçu et ce qu'il voit. Dans les deux cas, la correction existe : elle prend la forme d'un mouvement inverse ou d'une régularisation, tous deux datés, motivés et visibles. Un test d'intégration continue vérifie qu'aucun chemin applicatif ne permet la suppression ni la modification.

### 6.3 Séparation des tâches sur les flux physiques

La fraude sur stock dans une PME ne passe pas par une intrusion : elle passe par une régularisation d'inventaire saisie et validée par la même personne. Trois séparations sont donc imposées et paramétrables par seuil, sans possibilité de les désactiver globalement.

- Le compteur d'un inventaire ne valide pas l'écart qu'il constate au-delà d'un seuil défini par famille d'articles. Au-dessous du seuil, la validation est automatique et tracée ; au-dessus, elle requiert un second rôle.
- Le réceptionnaire ne valide pas la facture fournisseur correspondante. Le rapprochement à trois voies — commande, réception, facture — est vérifié par le système, l'écart au-delà d'une tolérance paramétrée bloquant le paiement.
- Le contrôleur qualité qui bloque un lot n'est pas nécessairement celui qui le libère, et la libération d'un lot bloqué par une non-conformité ouverte est refusée tant que l'action corrective n'est pas close.

### 6.4 Confinement du copilote, étendu

Le principe de la Phase 1 est inchangé : liste blanche d'outils en lecture seule, aucune génération de SQL, aucune action d'écriture, contrôleur d'outils côté code et non côté modèle, journalisation intégrale. La Phase 3 ajoute des outils de lecture sur le stock disponible, l'état d'un ordre de fabrication et l'avancement d'un dossier d'import. Elle en interdit explicitement trois catégories : tout outil touchant la paie, tout outil retournant une généalogie de lot — parce qu'une réponse approximative sur un rappel produit est pire que pas de réponse —, et tout outil déclenchant un mouvement, un blocage ou une libération. Le copilote informe ; il ne décide d'aucun flux physique.

## 7. UX, confort et travail sur le terrain

*Le poste de travail devient un couloir d'entrepôt*

### 7.1 Les contraintes réelles du poste

Les exigences d'expérience de la Phase 1 restent applicables et ne sont pas réécrites. La Phase 3 en ajoute cinq, qui découlent toutes du fait que l'utilisateur n'est plus assis devant un écran.

| Contrainte | Ce qu'elle impose | Comment elle est vérifiée |
|---|---|---|
| **Une seule main** | Le scanner occupe une main. Tout parcours terrain doit être réalisable sans clavier, avec des cibles tactiles larges et un enchaînement automatique après scan. | Parcours UC15 à UC17 exécutés sans saisie clavier en recette ; cibles ≥ 44 px vérifiées. |
| **Réseau intermittent** | La saisie continue hors ligne et se réconcilie sans doublon ni perte, sur le protocole du POS. | Test de coupure et de reprise automatisé sur réception, transfert, inventaire et déclaration d'atelier (STK-9). |
| **Cadence élevée** | Le retour visuel après un scan doit être immédiat et sans ambiguïté : accepté, refusé, ou attention. Un chargement de deux secondes par colis rend l'outil inutilisable. | Retour visuel sous 300 ms en local, indépendamment de l'état du réseau. |
| **Erreur coûteuse** | Une confusion de lot ou d'emplacement a un coût physique. Les écrans terrain confirment l'identité de ce qui est scanné plutôt que de supposer. | Affichage systématique de l'article, du lot et de la date limite après scan, avant validation. |
| **Environnement difficile** | Lumière variable, écran sale, gants. Contraste élevé, densité réduite, pas d'information portée par la seule couleur. | Contraste WCAG AA vérifié ; mode terrain à densité réduite proposé par défaut sur tablette. |

### 7.2 Douze composants nouveaux

La bibliothèque de la Phase 1 couvre le reste. Douze composants seulement sont ajoutés — à comparer aux vingt de la Phase 1 et aux neuf de la Phase 2 — et chacun répond à un besoin qu'aucun composant existant ne couvre.

| Composant | Rôle |
|---|---|
| **c-scan-input** | Champ de saisie au scan : capture le flux du lecteur, distingue un code-barres d'une frappe manuelle, enchaîne automatiquement, émet un retour visuel et sonore immédiat. |
| **c-lot-picker** | Sélection de lot avec date limite, quantité disponible et ordre FEFO proposé ; refuse un lot bloqué et affiche pourquoi. |
| **c-bin-map** | Plan simplifié des emplacements d'un dépôt, avec occupation et suggestion de rangement. |
| **c-qty-dual** | Champ quantité à double unité (unité de stock et unité d'achat ou de vente), avec conversion affichée en clair pour éviter l'erreur d'un facteur. |
| **c-uom-converter** | Éditeur de conversions d'unités d'un article, avec vérification de cohérence des facteurs. |
| **c-bom-tree** | Arborescence de nomenclature à plusieurs niveaux, dépliable, avec quantités développées et coût cumulé. |
| **c-workshop-board** | Tableau d'atelier par étape, dérivé du kanban existant, avec en-cours, retards et déclaration rapide au doigt. |
| **c-control-checklist** | Liste de points de contrôle avec saisie de mesure, limites critiques affichées et alerte immédiate au dépassement. |
| **c-recall-tree** | Arbre de généalogie amont et aval d'un lot, avec sélection du périmètre impacté et export daté. |
| **c-timesheet-grid** | Grille de pointage et d'absences par salarié et par jour, avec totaux et anomalies signalées. |
| **c-payslip-viewer** | Bulletin lisible, chaque ligne dépliable sur sa base de calcul, son taux et le paramètre appliqué à la date. |
| **c-landed-cost** | Ventilation d'un coût débarqué sur les lignes d'une réception, par clé au choix, avec contrôle de somme. |

### 7.3 Mode dégradé et file de saisie

Le mode dégradé de la Phase 3 réutilise le protocole du POS et n'en invente aucun (H19). Il en diffère sur un point : les saisies sont moins nombreuses mais plus longues et plus souvent interrompues — une réception de trente lignes peut s'étaler sur une heure, avec des coupures au milieu. Trois conséquences de conception :

- **La file est persistante et visible.** L'utilisateur voit combien de saisies attendent d'être envoyées et depuis quand. Une file invisible produit une confiance qui s'effondre au premier doute.
- **La réconciliation est explicite en cas de conflit.** Si le stock a changé entre la saisie et l'envoi, la ligne concernée est présentée pour arbitrage plutôt qu'appliquée en force ou rejetée en silence.
- **La numérotation est préfixée par le poste**, comme pour les caisses, ce qui garantit l'absence de collision sans coordination réseau.

### 7.4 Accessibilité et internationalisation

Les exigences de la Phase 1 sont maintenues : navigation clavier complète sur les écrans de bureau, focus visible, rôles ARIA sur les composants nouveaux, contraste WCAG AA. Le budget d'accessibilité explicite provisionné en Phase 1 est reconduit pour les douze composants nouveaux, au sprint 37, plutôt que supposé couvert. Côté langue, le français reste prioritaire ; la Phase 3 ajoute une exigence particulière : **les libellés des écrans terrain doivent être traduisibles en malgache en priorité** sur les autres écrans, parce que la population d'utilisateurs concernée est celle pour laquelle le français est le moins souvent la langue de travail.

## 8. Gouvernance des données

*Deux régimes de rétention qui ne se ressemblent pas*

### 8.1 Classification des données ajoutées

| Donnée | Classification | Conséquence |
|---|---|---|
| **Rémunération individuelle, situation familiale, absences pour raison de santé, identifiants d'organismes sociaux** | Personnelle sensible | Cloisonnement (6.1), chiffrement au repos et en transit, minimisation de l'affichage, journalisation des consultations, rétention légale distincte, inscription au registre des traitements. |
| **Généalogie de lot, décisions de libération, journal de rappel** | À valeur probante | Intégrité prioritaire sur la commodité (6.2) ; conservation au moins aussi longue que la durée de vie du produit concerné ; jamais purgée par un archivage automatique. |
| **Dossier d'import, liasse documentaire, conditions bancaires** | Financière confidentielle | Accès restreint au rôle achats et à la direction ; pas d'export planifié ni de diffusion par le canal ; conservation alignée sur la durée de reprise fiscale. |
| **Nomenclature, gamme, coût de revient** | Secret d'affaires | Ce sont les données que la concurrence paierait pour obtenir. Accès par rôle, export journalisé, exclusion du périmètre des outils IA agrégés. |
| **Mouvement de stock** | Opérationnelle | Volume élevé, sensibilité faible à l'unité, mais valeur probante par agrégation. Ne se supprime pas ; s'archive par exercice sans perdre la reconstituabilité. |

### 8.2 Rétention

**Aucune durée légale n'est écrite dans ce document.** Les durées de conservation applicables — pièces de paie, documents sociaux, archives fiscales et douanières, traçabilité des denrées — relèvent de textes qui ne sont pas vérifiés à la rédaction et qui diffèrent selon la nature du document. Les inventer serait une faute : une durée trop courte expose le client, une durée trop longue lui fait conserver des données personnelles sans base légale. Le produit livre donc un mécanisme — une politique de rétention par nature de document, portée par les paramètres versionnés de la Phase 1, avec purge planifiée et journalisée — et les valeurs sont renseignées et validées avec l'expert-comptable au sprint 33, au même moment que les barèmes de paie.

Trois principes encadrent ce mécanisme, indépendamment des durées retenues. D'abord, **l'obligation de conservation l'emporte sur la demande d'effacement** : une demande de suppression de données d'un ancien salarié ne peut pas supprimer les pièces de paie dont la conservation est obligatoire, et le refus doit être motivé et tracé. Ensuite, **l'archivage n'est pas la suppression** : un exercice archivé sort des index actifs sans cesser d'être restituable, ce qui est la condition pour qu'une généalogie reste calculable des années plus tard. Enfin, **la purge est journalisée** : ce qui a été supprimé, quand et sur quelle règle.

### 8.3 Qualité et contrôles bloquants

La Phase 2 avait introduit le contrôle de réconciliation bloquant avant publication d'un rafraîchissement. La Phase 3 étend ce principe au flux physique : un contrôle qui alerte sans bloquer finit par être ignoré, et un stock faux qui alerte tous les jours n'alerte plus.

| Contrôle | Nature | Comportement |
|---|---|---|
| **Stock négatif après mouvement** | Bloquant | Le mouvement est refusé, sauf dérogation explicite par rôle, motivée et journalisée. |
| **Agrégat de stock ≠ recalcul depuis les mouvements** | Bloquant | Contrôle nocturne ; toute divergence suspend la publication des indicateurs de stock et remonte en incident. |
| **Compte de stock comptable ≠ valorisation** | Bloquant | Empêche la clôture de période tant que l'écart n'est pas expliqué ou régularisé. |
| **Somme des ventilations de coût débarqué ≠ total des coûts annexes** | Bloquant | La réception ne peut pas être valorisée tant que la ventilation n'est pas complète (ACH-7). |
| **Rendement d'un ordre hors bornes paramétrées** | Alertant | Signalé au chef d'atelier et au contrôle de gestion ; n'empêche pas la clôture, mais exige un motif. |
| **Variation anormale d'un net de paie d'un mois sur l'autre** | Bloquant à la publication | Le cycle ne peut pas être publié tant que chaque anomalie n'est pas visée ou justifiée (PAY-7). |
| **Lot dont la date limite est dépassée et qui reste disponible** | Alertant | Alerte quotidienne et exclusion automatique du FEFO ; blocage automatique paramétrable par famille. |

### 8.4 Sauvegarde et reprise

La politique de la Phase 1 est inchangée, avec deux extensions. La restauration réelle périodique, déjà obligatoire, doit désormais inclure la vérification qu'une généalogie de lot est reconstituable après restauration — c'est le seul test qui prouve que la sauvegarde couvre ce qui a une valeur probante. Et la sauvegarde des données de paie fait l'objet d'une vérification de chiffrement distincte, la restauration d'un journal de paie en clair dans un environnement de test étant un incident de confidentialité même sans fuite externe.

## 9. Interopérabilité et outils tiers

*Beaucoup d'échanges, aucune interface machine*

### 9.1 Matériel de terrain

| Matériel | Mode de raccordement | Justification et limite |
|---|---|---|
| **Lecteur de codes-barres** | Émulation clavier, sur tablette ou poste. Aucun pilote, aucune extension. | Même principe que le POS en Phase 1 : le parc est hétérogène et non certifié. La contrepartie est qu'un lecteur mal configuré se comporte comme une frappe rapide — d'où la détection dans c-scan-input. |
| **Imprimante d'étiquettes** | Flux d'impression standard depuis le navigateur ou fichier d'étiquette téléchargé. | Évite un service d'impression à installer sur chaque poste. Limite assumée : la mise en page fine dépend du modèle, et un gabarit par modèle utilisé doit être paramétré à la mise en service. |
| **Balance connectée, terminal portable durci, tiroir-caisse piloté** | Hors périmètre, comme en Phase 1. | Chacun impose un composant local. La pesée est saisie ; le gain d'une intégration ne justifie pas la charge d'exploitation à cette échelle. |

### 9.2 Échanges externes

| Tiers | Mode retenu | Ce qui est livré, et ce qui ne l'est pas |
|---|---|---|
| **Banque (crédit documentaire)** | Documentaire. Statuts saisis, pièces jointes rattachées au dossier. | **Livré** : cycle de vie complet du CREDOC, liasse documentaire, échéances et alertes, conditions et frais. **Non livré** : transmission ou réception automatique d'un message bancaire. Hypothèse H14 à lever au sprint 12. |
| **Douane et transitaire** | Documentaire. Référence de déclaration, droits et taxes liquidés, documents. | **Livré** : rattachement au dossier d'import et intégration des droits au coût débarqué. **Non livré** : établissement ou dépôt d'une déclaration. Le périmètre d'interface éventuel n'est pas vérifié (H15). |
| **Organismes sociaux et administration fiscale** | Documentaire. États et fichiers produits par WideHalo, déposés hors de l'outil. | **Livré** : les états déclaratifs reconstitués depuis le journal de paie, avec leur date d'arrêté. **Non livré** : télédéclaration. Formats à vérifier au sprint 31 (H18). |
| **Banque (paiement des salaires)** | Fichier ou état d'ordre de virement exportable. | **Livré** : l'ordre et son état de rapprochement. **Non livré** : l'exécution du paiement, ni vers une banque, ni vers un opérateur de monnaie électronique. |
| **Canal de messagerie (acquis Phase 2)** | Adaptateur existant, modèles approuvés, consentement. | Accusé de commande fournisseur, alerte de péremption, notification de rappel, mise à disposition du bulletin. Canal de confort : aucun processus de la Phase 3 n'en dépend, et son indisponibilité ne bloque rien. |

### 9.3 Règle de gouvernance des échanges

La règle posée en Phase 1 et confirmée en Phase 2 s'applique sans changement : **l'ERP reste intégralement fonctionnel sans aucun de ces échanges.** Aucun n'est sur un chemin critique, et chacun se dégrade en saisie manuelle. C'est ce qui permet d'accepter que quatre d'entre eux reposent sur des hypothèses encore ouvertes : si H14, H15 ou H18 se révèlent fausses, le produit perd une commodité, pas une fonction. La conséquence en conception est que chaque échange est modélisé comme un document rattaché et un statut saisissable avant d'être, éventuellement un jour, automatisé.

## 10. Scalabilité

*Le volume change de nature : la ligne de mouvement remplace la ligne de document*

| Dimension | Situation Phase 3 | Seuil où elle devient un problème | Option prévue |
|---|---|---|---|
| **Volume de mouvements** | Dimension dominante. Chaque vente, chaque réception, chaque consommation d'atelier et chaque prélèvement produit une ou plusieurs lignes. Le POS et l'atelier sont les deux contributeurs principaux. | Lenteur du calcul de disponibilité ou de la généalogie ; fenêtre de rafraîchissement analytique dépassée. | Partitionnement du mouvement par exercice dès la conception ; agrégat de stock matérialisé ; index ciblés sur lot, emplacement et date ; archivage par exercice sans perte de reconstituabilité. |
| **Profondeur de généalogie** | Nouvelle dimension. Un lot de produit fini peut dépendre de dizaines de lots amont sur plusieurs niveaux. | Traçabilité aval au-delà de 5 secondes sur un cas réel, ou explosion du nombre de chemins sur un produit très composé. | Parcours de graphe borné en profondeur et en largeur, avec pagination du résultat ; table de correspondance matérialisée par lot fini si le seuil est atteint ; mesure obligatoire en recette (QUA-4). |
| **Calcul de besoins** | Développement de nomenclature sur l'ensemble du portefeuille, croisé avec la prévision et le stock. | Durée incompatible avec la fenêtre nocturne, ou concurrence avec le rafraîchissement analytique et le modèle de langage local. | Exécution planifiée hors des heures ouvrées et hors créneau du modèle local ; calcul par famille plutôt que global ; profondeur de nomenclature bornée et signalée. |
| **Cycle de paie** | Charge en pointe, très concentrée : tout le calcul se fait en un ou deux jours par mois. | Durée de calcul d'un cycle perceptible au-delà de quelques dizaines de salariés, ou verrouillage prolongé pendant le calcul. | Calcul par lots en tâche de fond avec avancement visible ; le cycle est isolé du reste de l'application ; l'ordre de grandeur visé (jusqu'à 150 salariés) ne justifie aucune optimisation au-delà. |
| **Équipe de développement** | Toujours une personne, qui supporte deux phases en production. Dimension la plus contraignante, et elle se dégrade. | Déjà atteinte : la capacité hebdomadaire passe de 4,5 à 4 jours effectifs. | Découpage en deux vagues avec mise en production intermédiaire ; quatre moteurs plutôt que cinq modules de code ; douze composants nouveaux seulement ; budgets vérifiés en CI. |
| **Nombre de tenants** | Le travail nocturne devient la somme du rafraîchissement analytique, du calcul de besoins et du contrôle de cohérence, par tenant. | La nuit ne suffit plus au-delà de quelques dizaines de tenants actifs avec production. | Séquencement par tenant avec priorité ; calcul de besoins hebdomadaire plutôt que quotidien pour les tenants sans rotation rapide ; isolation d'un tenant volumineux sur sa propre instance, sans changement de code. |

### 10.1 Budgets d'architecture révisés

| Budget | Fin Phase 2 | Révisé Phase 3 | Justification |
|---|---|---|---|
| **Modèles** | 285 | 380 | ≈ 12 pour le socle d'inventaire (unité, conversion, dépôt, zone, emplacement, lot, série, mouvement, agrégat, couche de valorisation, réservation, règle de réapprovisionnement) ; ≈ 14 pour les achats et l'import ; ≈ 16 pour la production ; ≈ 12 pour la qualité ; ≈ 22 pour la paie ; ≈ 10 pour les faits analytiques et l'extension de prévision. La paie est le poste le plus lourd et le plus difficile à réduire. |
| **Endpoints** | 840 | 1 060 | Fragments d'écrans terrain, points de terminaison de synchronisation hors ligne pour l'entrepôt et l'atelier, endpoints de scan, outils analytiques du copilote — hors paie. |
| **Écrans (total)** | 180 | 245 | Écrans de stock et d'entrepôt, dossiers d'achat et d'import, atelier et ordres de fabrication, contrôles et rappels, dossier salarié et cycle de paie. |
| **Écrans legacy** | 0 | 0 — maintenu | Inchangé depuis la Phase 1. Aucun écran de la Phase 3 ne crée de dette d'interface. |
| **Rapports** | plafond fixé en Phase 2 | + 25 au maximum | L'incrément est arbitré au sprint 1, rapport par rapport, sur le même principe qu'en Phase 2 : ajouter un rapport oblige à en retirer un ou à le rendre paramétrable. |
| **Rubriques de paie** | — | plafond fixé au sprint 29 | Nouveau budget. Une table de rubriques dérive exactement comme un catalogue de rapports : chaque cas particulier client ajoute une rubrique, personne n'en retire jamais, et au bout de deux ans plus personne ne sait laquelle s'applique. Le plafond force à paramétrer plutôt qu'à dupliquer. |

**Pourquoi le budget de modèles augmente de 95 alors que la Phase 2 n'en ajoutait que 40.** Parce que la Phase 3 est la seule des trois à ajouter des domaines et non des vues sur un domaine existant. La Business Intelligence relisait des données déjà modélisées ; le stock, la production et la paie modélisent des réalités qui n'existaient pas dans le produit. Ce rehaussement est donc légitime — mais il porte le total près du double de la cible initiale de la refonte, et c'est le signal qu'au-delà de la Phase 3, toute nouvelle fonctionnalité devra se construire par paramétrage des moteurs existants plutôt que par ajout d'entités.

## 11. Choix technologiques

*Trois décisions, toutes orientées par la contrainte solo et par l'explicabilité*

### 11.1 Méthode de valorisation du stock

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **Coût unitaire moyen pondéré (CUMP)** | Une seule valeur par article, calcul simple et rejouable, écriture comptable directe, admis par le référentiel, compréhensible par un dirigeant sans formation comptable. | Lisse les variations de prix d'achat, ce qui masque partiellement l'effet d'un change défavorable sur une importation ponctuelle. | **Retenu** comme méthode unique livrée. |
| **FIFO par lot, en valeur** | Reflète fidèlement le coût réel des unités sorties ; naturel là où le lot existe déjà pour la traçabilité. | Impose une couche de valorisation par couche de stock, un rejeu beaucoup plus coûteux et une réconciliation comptable plus délicate. Complexité difficile à justifier si aucun client ne la demande. | Option paramétrable, développée seulement si H13 le justifie (arbitrage au sprint 3). |
| **Coût standard avec écarts** | Excellent outil de pilotage industriel : l'écart sur coût matière et sur coût de main-d'œuvre est isolé. | Suppose une comptabilité analytique mature et un standard révisé périodiquement — deux conditions que les clients visés ne remplissent pas. Le coût standard non révisé produit des écarts que personne n'exploite. | Écarté pour la Phase 3. Le coût prévu d'un ordre de fabrication en donne l'essentiel du bénéfice sans la mécanique. |
| **LIFO** | — | Non admis par le référentiel comptable applicable. | Écarté par principe. |

### 11.2 Calcul des besoins matière

| Option | Analyse | Verdict |
|---|---|---|
| **Calcul en base, par développement de nomenclature et confrontation au stock et à l'en-cours** | Aucun composant supplémentaire ; s'exécute dans la file de worker existante ; résultat explicable ligne à ligne, ce qui est la condition pour qu'un acheteur suive une proposition. | **Retenu.** |
| **Solveur d'optimisation externe** | Optimiserait le coût total d'approvisionnement sous contraintes. Ajoute une dépendance, un modèle à calibrer et un résultat que personne dans l'entreprise cliente ne saura contester. | Écarté. Une proposition inexplicable n'est pas suivie, quelle que soit sa qualité. |
| **Ordonnancement à capacité finie** | Répondrait à la charge d'atelier de façon exacte plutôt que projetée. Suppose des gammes fiables, des temps mesurés et une discipline de déclaration que les ateliers visés n'ont pas encore. | Écarté du périmètre (2.5). La charge projetée par poste couvre le besoin réel : savoir si l'on tiendra le mois. |

### 11.3 Moteur de paie

| Option | Analyse | Verdict |
|---|---|---|
| **Moteur de rubriques paramétrées, adossé aux paramètres versionnés de la Phase 1** | Un changement de barème est une modification de données, datée et auditée, sans livraison ni non-régression. Le bulletin reste explicable ligne à ligne, chaque ligne pointant vers le paramètre appliqué à la date. Réutilise un acquis déjà en production. | **Retenu.** |
| **Logiciel de paie tiers, interfacé** | Économiserait le développement du moteur. Mais il faudrait synchroniser salariés, absences et imputations analytiques dans les deux sens, maintenir deux référentiels de rôles, et le client paierait deux abonnements. La ressaisie que la Phase 3 doit supprimer réapparaîtrait à la frontière. | Écarté. Repli envisageable pour un client disposant déjà d'un outil qu'il ne veut pas quitter, sous forme d'import du journal de paie uniquement. |
| **Règles écrites en code** | Plus rapide à écrire pour le premier client. Impose une livraison à chaque loi de finances, à chaque convention particulière et à chaque prime nouvelle — sur un produit multi-tenant, c'est une impasse dès le troisième client. | Écarté par principe, comme le text-to-SQL en Phase 1. |

### 11.4 Briques confirmées sans réexamen

Django et son ORM, django-ninja, PostgreSQL, HTMX et Alpine.js, la bibliothèque de composants, le gateway IA en FastAPI, l'hébergement Hetzner via Coolify et Caddy, la production de documents PDF et le service worker du POS sont confirmés sans réexamen. Aucun élément de la Phase 3 ne les met en tension : la charge nouvelle est en volume de lignes et en complexité métier, pas en nature de traitement. Le seul point à surveiller est la coexistence sur une instance PostgreSQL unique de la charge transactionnelle, de la charge analytique de la Phase 2 et du volume de mouvements de la Phase 3 — c'est le risque P3-R3, dont le repli reste celui identifié en Phase 2.

## 12. Socle d'inventaire et modèle de mouvement

*La partie du document à lire avant d'écrire la moindre ligne de code*

Cette section joue pour la Phase 3 le rôle que la couche sémantique jouait pour la Phase 2 : elle définit la structure dont dépendent tous les modules, et une erreur commise ici ne se corrige plus après le sprint 10. Elle est livrée par le bloc A, avant tout écran métier.

### 12.1 Le mouvement comme écriture unique

Un mouvement de stock est un enregistrement immuable qui porte : le tenant, l'article, la quantité en unité de stock, l'orientation (entrée, sortie, transfert), l'emplacement d'origine et de destination, le lot ou le numéro de série le cas échéant, la date d'effet, la nature, la pièce d'origine et son module, l'utilisateur, et la valeur unitaire retenue par le moteur de valorisation.

- **Toute variation passe par lui.** Réception d'achat, retour fournisseur, transfert, prélèvement, expédition, vente au comptoir, consommation d'atelier, entrée de production, sous-produit, rebut, casse, régularisation d'inventaire : douze natures, une table.
- **Il ne se supprime ni ne se modifie.** Une annulation est un mouvement inverse, portant la référence du mouvement annulé et son motif.
- **Un transfert est un mouvement unique à deux emplacements**, et non deux mouvements appariés. C'est ce qui garantit qu'un transfert ne peut pas être à moitié réalisé, y compris après une coupure réseau en mode dégradé.
- **La date d'effet est distincte de la date de saisie.** Le mode dégradé impose de pouvoir enregistrer aujourd'hui un mouvement effectué hier ; les deux dates sont conservées, et la valorisation utilise la date d'effet.

### 12.2 Unités de mesure et conversions

Chaque article a une unité de stock unique et immuable après le premier mouvement — la changer invaliderait tout l'historique. Il peut avoir des unités d'achat et de vente distinctes, avec un facteur de conversion déclaré et vérifié. Deux règles closent les erreurs les plus courantes : **le mouvement est toujours enregistré en unité de stock**, la conversion se faisant à la saisie et étant affichée en clair ; et **une conversion à facteur variable est interdite**, ce qui exclut les unités dont le rapport dépend du lot. Pour l'agroalimentaire, où le cas se présente réellement — un sac dont le poids varie —, la pesée est saisie et devient la quantité, elle n'est pas déduite d'un facteur.

### 12.3 Lot, série, emplacement et réservation

| Notion | Règle de gestion |
|---|---|
| **Lot** | Porté par le mouvement. Créé à la réception ou à l'entrée de production, avec sa date limite de consommation ou d'utilisation optimale et son origine. Un article est déclaré géré par lot ou non ; le passage de non à oui n'est possible qu'à stock nul, et l'écran l'explique plutôt que de refuser sans motif. |
| **Numéro de série** | Cas particulier du lot à quantité unitaire. Même mécanique, sans table distincte : un numéro de série est un lot dont la quantité vaut un et dont l'unicité est contrainte. |
| **Emplacement** | Hiérarchie dépôt → zone → emplacement, à trois niveaux au plus. Un article peut être présent dans plusieurs emplacements ; la disponibilité est la somme des emplacements non bloqués, diminuée des réservations. |
| **Réservation** | Une commande client confirmée, un ordre de fabrication lancé ou une préparation en cours réservent la quantité. La réservation est une ligne rattachée à sa pièce, jamais un mouvement : elle n'a aucun effet comptable et disparaît avec sa pièce. |
| **Blocage** | Un lot bloqué par la qualité reste en stock et reste valorisé, mais sort de la disponibilité et du FEFO. Le déblocage est une décision tracée, jamais un effet de bord d'une autre action. |
| **Règle de prélèvement** | FEFO par défaut sur les articles gérés par lot avec date limite ; FIFO à défaut de date ; sélection manuelle possible mais motivée et journalisée, parce que c'est exactement là que se produisent les erreurs de péremption. |

### 12.4 Valorisation et inventaire permanent

- Le CUMP est recalculé à chaque entrée valorisée, à partir du stock et de la valeur antérieurs. Les sorties sont valorisées au CUMP en vigueur à la date d'effet.
- **Le coût débarqué entre dans le CUMP, pas à côté.** Une réception d'import n'est définitivement valorisée qu'une fois les coûts annexes ventilés ; jusque-là, elle est valorisée provisoirement et l'écart est repris à la ventilation (ACH-7).
- Chaque mouvement produit ou prépare une écriture d'inventaire permanent selon le paramétrage du client, en utilisant le référentiel comptable abstrait de la Phase 1. Aucune logique comptable nouvelle n'est écrite.
- **La valeur de stock à toute date est calculable par rejeu des mouvements.** C'est ce qui permet de justifier un état de stock antérieur sans conserver un instantané par jour.
- Un rapprochement bloquant compare le compte de stock comptable à la valorisation à chaque clôture de période. Un écart empêche la clôture tant qu'il n'est pas expliqué ou régularisé.

**Le stock initial est le point de fragilité de toute la phase.** Le CUMP est récursif : la valeur d'aujourd'hui dépend de celle d'hier, indéfiniment. Si le stock initial est faux en quantité ou en valeur, l'erreur ne se corrige jamais d'elle-même — elle se dilue lentement, sans jamais disparaître, et elle contamine le coût de revient de chaque produit fabriqué. La mise en service impose donc un inventaire physique complet et daté par dépôt, avec une valorisation d'entrée justifiée (dernier prix d'achat connu, à défaut valeur d'expert), validée par le comptable du client et figée. Ce n'est pas une tâche de développement, c'est une condition d'entrée en production, et elle figure comme telle en section 17.4.

### 12.5 Extension du modèle dimensionnel

La condition posée en Phase 2 était que le modèle en étoile accueille les faits de la Phase 3 sans reprise. Cette section la vérifie plutôt que de la supposer, au sprint 2. Quatre faits nouveaux sont ajoutés, tous rattachés aux dimensions conformes existantes — temps, tiers, article, point de vente, compte, utilisateur — éventuellement enrichies mais jamais restructurées.

| Fait ajouté | Grain | Ce qu'il permet de restituer |
|---|---|---|
| **Fait mouvement de stock** | La ligne de mouvement. | Rotation, couverture en jours, valeur de stock, taux de service, casse et démarque, sorties par nature. |
| **Fait réception et achat** | La ligne de réception, rattachée à sa commande et à son dossier d'import. | Délai fournisseur réel, taux de conformité des livraisons, coût débarqué unitaire, exposition au change. |
| **Fait ordre de fabrication** | L'opération réalisée et la consommation déclarée. | Rendement réel contre théorique, taux de conformité au premier passage, charge par poste, écart de coût de fabrication. |
| **Fait paie** | La ligne de bulletin, agrégée par rubrique et par centre de charge. | Coût du personnel par centre, masse salariale et son évolution, imputation de la main-d'œuvre au coût de production. Accès restreint au rôle paie, y compris en agrégé. |

Les indicateurs correspondants sont déclarés dans le dictionnaire d'indicateurs de la Phase 2 avant tout affichage, selon la règle inchangée : un indicateur, une définition, dans tout le produit. Un taux de rotation calculé dans un écran de stock et différemment dans un tableau de bord de direction serait exactement la divergence que la Phase 2 a été construite pour éliminer.

## 13. Spécifications fonctionnelles — Phase 3

*Cinquante-neuf critères, écrits pour être traduits en tests*

Chaque module est décrit par ses écrans, ses règles de gestion et ses critères d'acceptation numérotés. Les critères sont écrits pour être automatisables sans reformulation : c'est la condition pour qu'ils soient réellement vérifiés en intégration continue plutôt que constatés à l'œil en recette.

### 13.1 Module Stock et entrepôt

**Objectif** : que la quantité affichée soit la quantité physique. Le risque de ce module n'est pas technique — il est d'ergonomie de terrain : si la saisie est plus lente que le cahier, elle sera faite le soir, de mémoire, et le stock sera faux.

| Écran | Contenu et interactions |
|---|---|
| **Réception** | Ouverture depuis une commande d'achat ou en réception libre. Scan de l'article, saisie ou scan du lot, date limite, quantité, emplacement de rangement suggéré. Réception partielle, surlivraison avec tolérance paramétrée, écart signalé à la ligne. Impression d'étiquettes de lot. |
| **Transfert** | Scan de l'emplacement d'origine, de l'article, de l'emplacement de destination. Transfert entre emplacements ou entre dépôts, ce dernier passant par un état « en transit » qui rend la quantité indisponible sans la faire disparaître. |
| **Préparation et expédition** | Liste des lignes à prélever ordonnée par emplacement, lot proposé par FEFO, scan de confirmation à chaque ligne. Écart de préparation motivé. Génération du bon de livraison, rattaché à la commande de la Phase 1. |
| **Inventaire** | Session d'inventaire tournant par zone, par famille ou par article, ou inventaire complet avec gel des mouvements sur le périmètre. Comptage à l'aveugle par défaut — le compteur ne voit pas la quantité attendue. Écarts présentés pour validation, régularisation par mouvement. |
| **Consultation de stock** | Stock par article, par emplacement, par lot, avec disponible, réservé, bloqué et en transit distingués. Historique des mouvements d'un article avec sa pièce d'origine. Valeur de stock à une date. |
| **Règles de réapprovisionnement** | Par article et par dépôt : stock de sécurité, point de commande, quantité de réapprovisionnement, délai fournisseur. Alimente la proposition du bloc Forecast (13.6). |
| **Écran magasinier tablette** | Vue à densité réduite, cibles larges, quatre actions au maximum : recevoir, ranger, prélever, compter. Indicateur de file de saisie hors ligne toujours visible. |

**Règles de gestion**

- Un mouvement qui rendrait le stock négatif est refusé, sauf dérogation par rôle, motivée et journalisée. Un stock négatif toléré est un stock faux qui se propage dans la valorisation.
- Le comptage d'inventaire est à l'aveugle par défaut. Afficher la quantité attendue transforme le comptage en confirmation, ce qui est la manière la plus efficace de ne rien détecter.
- Un écart d'inventaire au-delà du seuil de la famille exige une seconde validation par un rôle distinct de celui qui a compté (6.3).
- Un lot bloqué ou périmé est exclu du FEFO et de la disponibilité, sans quitter le stock ni la valorisation.
- Le transfert entre dépôts est un mouvement unique à deux emplacements, avec état de transit : il ne peut pas être à moitié réalisé.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **STK-1** | Un mouvement rendant le stock négatif est refusé ; avec la dérogation activée, il est accepté, porte un motif obligatoire et apparaît au journal d'audit. |
| **STK-2** | La somme des mouvements d'un article recalculée depuis zéro est strictement égale à l'agrégat de stock affiché, sur un jeu de trois exercices ; le contrôle nocturne détecte une divergence introduite volontairement. |
| **STK-3** | Une préparation sur un article géré par lot avec date limite propose systématiquement le lot dont la date est la plus proche ; un choix manuel différent exige un motif et est journalisé. |
| **STK-4** | Un lot bloqué n'apparaît ni dans le disponible, ni dans la proposition FEFO, ni dans une préparation, et reste présent dans la valeur de stock. |
| **STK-5** | Un transfert inter-dépôts interrompu entre le départ et l'arrivée laisse la quantité en transit, ni dans le dépôt d'origine ni dans celui de destination, et jamais perdue ni comptée deux fois. |
| **STK-6** | Une session d'inventaire à l'aveugle n'expose la quantité attendue à aucun moment au compteur, y compris par appel direct de l'API. |
| **STK-7** | Un écart d'inventaire supérieur au seuil de la famille ne peut pas être validé par l'utilisateur qui a saisi le comptage ; la tentative est refusée et journalisée. |
| **STK-8** | La validation d'un écart d'inventaire produit un mouvement de régularisation portant la référence de la session ; l'écart validé n'est plus modifiable. |
| **STK-9** | Une réception de trente lignes réalisée hors ligne, interrompue au milieu et reprise après reconnexion, produit exactement trente mouvements, sans doublon ni perte, avec les dates d'effet saisies. |
| **STK-10** | Le parcours de réception complet est exécutable sans clavier, au scanner seul, avec un retour visuel sous 300 ms après chaque scan indépendamment de l'état du réseau. |
| **STK-11** | Un article dont l'unité de stock est changée après le premier mouvement voit l'opération refusée ; le passage d'un article de non géré par lot à géré par lot est refusé si son stock n'est pas nul. |
| **STK-12** | La valeur de stock à une date antérieure, recalculée par rejeu des mouvements, est égale au solde du compte de stock comptable à cette même date, à l'ariary près. |

### 13.2 Module Achats, import et CREDOC

**Objectif** : qu'un dossier d'import de six mois soit tenu dans l'outil plutôt que dans une boîte de courriels et un tableur, et que le coût débarqué soit calculé plutôt que reconstitué. Le risque de ce module est la dépendance à des tiers qui n'exposent aucune interface (H14, H15) : la conception l'assume en modélisant le dossier et ses statuts, jamais l'échange machine.

| Écran | Contenu et interactions |
|---|---|
| **Demande d'achat** | Saisie par le demandeur, circuit d'approbation par montant et par famille sur le moteur de workflow de la Phase 1, transformation en commande après approbation. |
| **Consultation fournisseur** | Envoi d'une demande de prix à plusieurs fournisseurs, saisie des réponses, comparatif sur prix, délai et conditions, attribution motivée. |
| **Commande d'achat** | Lignes en unité d'achat avec conversion affichée, devise et date de référence de change, conditions, date de livraison attendue, suivi du reste à recevoir. Accusé envoyé par le canal si le fournisseur y a consenti. |
| **Dossier d'import** | Conteneur du cycle complet : commande, incoterm, transitaire, expédition, documents, déclaration en douane et droits liquidés, coûts annexes, réception. Chronologie visible d'un coup d'œil. |
| **Crédit documentaire** | Cycle de vie du CREDOC en états successifs, de la demande d'ouverture au règlement, en passant par la domiciliation, la notification, l'expédition et la remise des documents. Chaque changement d'état est daté, motivé et documenté. Échéances et alertes. |
| **Coût débarqué** | Ventilation des coûts annexes — fret, assurance, droits et taxes, transit, manutention, écart de change — sur les lignes de réception, par clé au choix (valeur, poids, volume, quantité), avec contrôle de somme. |
| **Facture fournisseur** | Rapprochement à trois voies commande / réception / facture, écart par ligne, tolérance paramétrée, blocage au-delà. Écriture comptable sur le référentiel de la Phase 1. |

**Règles de gestion**

- Une réception d'import est valorisée provisoirement au prix d'achat converti, puis définitivement à la ventilation des coûts annexes. L'écart est repris dans le CUMP à cette date, jamais passé en charge sans trace.
- La ventilation d'un coût débarqué doit être complète : la somme ventilée est égale au total des coûts annexes, sans arrondi perdu. Le contrôle est bloquant.
- Les états du crédit documentaire suivent l'ordre du circuit bancaire ; un état ne peut pas être sauté, et un retour en arrière est une annulation motivée, pas une modification.
- Le réceptionnaire ne valide pas la facture correspondante (6.3).
- Le taux de change appliqué est celui de la date de référence du dossier, conservé avec le dossier. Un recalcul ultérieur au taux du jour rendrait le coût de revient instable.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **ACH-1** | Une demande d'achat au-dessus du seuil d'approbation ne peut pas devenir une commande sans l'approbation requise, y compris par appel direct de l'API. |
| **ACH-2** | Une réception partielle laisse un reste à recevoir exact ; la somme des réceptions successives ne peut pas dépasser la quantité commandée au-delà de la tolérance paramétrée. |
| **ACH-3** | Une ligne saisie en unité d'achat produit un mouvement en unité de stock avec le facteur de conversion déclaré, et la conversion est affichée à l'écran avant validation. |
| **ACH-4** | Le cycle de vie du crédit documentaire refuse toute transition non prévue par le circuit ; chaque transition porte une date, un motif et au moins un document lorsque l'état l'exige. |
| **ACH-5** | Un dossier d'import restitue en un écran la chronologie complète de ses événements, avec leurs pièces jointes, sans navigation vers un autre module. |
| **ACH-6** | Le taux de change conservé au dossier est celui de sa date de référence ; un recalcul déclenché plus tard ne modifie ni le coût débarqué ni le CUMP historique. |
| **ACH-7** | Une réception d'import ne peut pas être valorisée définitivement tant que la somme des ventilations de coûts annexes n'égale pas leur total ; l'écart de valorisation provisoire est repris dans le CUMP à la date de ventilation. |
| **ACH-8** | Le rapprochement à trois voies bloque le règlement d'une facture dont l'écart de prix ou de quantité dépasse la tolérance, et affiche l'écart ligne à ligne. |
| **ACH-9** | L'utilisateur ayant validé une réception ne peut pas valider la facture fournisseur correspondante ; la tentative est refusée et journalisée. |
| **ACH-10** | Le coût débarqué unitaire d'un article importé, restitué par le module analytique, est égal au coût calculé par le moteur de valorisation, à l'ariary près. |

### 13.3 Module Production

**Objectif** : connaître ce qui a été réellement consommé et réellement produit, et en déduire un coût de revient. Le risque de ce module est la déclaration : un atelier qui ne déclare pas produit des données inutiles. C'est pourquoi la déclaration tablette est traitée comme une exigence de premier rang, pas comme un écran secondaire.

| Écran | Contenu et interactions |
|---|---|
| **Nomenclature** | Arborescence à plusieurs niveaux, composants avec quantité et taux de perte. Deux variantes livrées : nomenclature de fabrication classique, et nomenclature de process agroalimentaire avec sous-produits, coproduits et rendement attendu. Pour le textile, consommation matière dépendante de la taille selon une courbe déclarée. |
| **Gamme et postes de charge** | Suite d'opérations avec poste, temps de préparation et temps unitaire, possibilité de sous-traitance de façon sur une opération. Le poste de charge porte une capacité indicative, utilisée pour la projection de charge et non pour un ordonnancement. |
| **Ordre de fabrication** | Article à produire, quantité, nomenclature et gamme retenues, dates prévues, réservation des composants, coût prévu. États : brouillon, lancé, en cours, terminé, clôturé, annulé. |
| **Kanban d'atelier** | Colonnes par étape de la gamme, cartes par ordre, en-cours et retards visibles, déplacement au doigt qui change l'état et journalise au chatter. Optimisé tablette. |
| **Déclaration** | Consommation réelle par composant et par lot, production réalisée avec création du lot fini, rebut avec motif, temps passé par opération. Trois gestes maximum pour une déclaration standard. |
| **Sous-traitance de façon** | Sortie de matière vers un façonnier, suivi de l'en-cours chez le tiers, retour du produit façonné, valorisation de la prestation. La matière chez le façonnier reste au stock de l'entreprise, dans un emplacement dédié. |
| **Coût de revient et rendement** | Coût prévu contre coût réel par ordre : matière au CUMP, main-d'œuvre imputée, sous-traitance. Rendement réel contre théorique, taux de conformité au premier passage, écarts commentés. |

**Règles de gestion**

- Une consommation d'atelier est un mouvement de sortie ; une production est un mouvement d'entrée avec création de lot. Aucun compteur parallèle.
- Un ordre lancé réserve ses composants ; la réservation est libérée à la clôture ou à l'annulation, jamais oubliée.
- La déclaration de production crée le lot fini et l'attache aux lots des composants consommés : c'est cet attachement qui rend la généalogie calculable.
- Un rebut est déclaré avec un motif issu d'une liste paramétrée. Un rebut sans motif est un rebut qu'on ne réduira jamais.
- La clôture d'un ordre fige le coût réel et l'écart au coût prévu ; un ordre clôturé n'accepte plus de déclaration.
- Pour la nomenclature de process, la somme des rendements des produits et sous-produits est contrôlée contre la quantité de matière engagée, avec une tolérance paramétrée.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **PRD-1** | Le développement d'une nomenclature à trois niveaux restitue les quantités développées exactes, taux de perte inclus, et signale une nomenclature récursive au lieu de boucler. |
| **PRD-2** | Pour un style textile, la consommation matière calculée pour une répartition de tailles donnée suit la courbe déclarée et diffère effectivement d'une taille à l'autre. |
| **PRD-3** | Le lancement d'un ordre réserve les composants ; sa clôture ou son annulation libère intégralement les réservations restantes, vérifié par comparaison du disponible avant et après. |
| **PRD-4** | Une déclaration de production crée le lot fini et l'attache aux lots consommés ; la généalogie amont du lot fini restitue exactement ces lots, sans en omettre ni en ajouter. |
| **PRD-5** | Le déplacement d'une carte sur le kanban change l'état de l'ordre, journalise l'événement au chatter avec son auteur, et fonctionne sur tablette en réseau dégradé. |
| **PRD-6** | Le taux de conformité au premier passage est calculé depuis les déclarations réelles et non saisi ; il est recalculable à l'identique depuis les mouvements. |
| **PRD-7** | Sur une nomenclature de process, un écart entre la matière engagée et la somme des produits, sous-produits et rebuts supérieur à la tolérance déclenche une alerte et exige un motif à la clôture. |
| **PRD-8** | La matière sortie vers un façonnier reste dans la valeur de stock de l'entreprise, dans un emplacement de sous-traitance, et n'apparaît pas dans le disponible du dépôt principal. |
| **PRD-9** | Le coût réel d'un ordre clôturé est égal à la somme des consommations valorisées au CUMP à leur date d'effet, de la main-d'œuvre imputée et de la sous-traitance, à l'ariary près. |
| **PRD-10** | Un ordre clôturé refuse toute déclaration de consommation ou de production ultérieure, y compris par appel direct de l'API. |

### 13.4 Module Qualité et HACCP

**Objectif** : pouvoir prouver. Ce module produit peu d'écrans et beaucoup d'exigences d'intégrité : sa valeur ne se manifeste qu'un jour, celui d'un rappel ou d'un audit client, et ce jour-là un journal approximatif ne vaut rien.

| Écran | Contenu et interactions |
|---|---|
| **Plan de contrôle** | Points de contrôle par article, par étape de gamme ou par réception, avec nature de la mesure, limites critiques, fréquence et responsable. Les points de contrôle critiques au sens HACCP sont marqués comme tels et ne peuvent pas être ignorés. |
| **Prélèvement et mesure** | Liste des contrôles dus, saisie de la mesure sur tablette, alerte immédiate au dépassement d'une limite critique, pièce jointe (photo, certificat). |
| **Blocage et libération** | Décision sur un lot : bloqué, sous réserve, libéré. Motif obligatoire, horodatage serveur, identité. Effet immédiat sur la disponibilité. |
| **Non-conformité et action corrective** | Ouverture d'une non-conformité rattachée à un lot, un fournisseur ou un ordre ; analyse, action corrective avec responsable et échéance sur le moteur de workflow, clôture. |
| **Certificat fournisseur** | Rattachement d'un certificat d'analyse à un lot reçu, avec date de validité ; blocage automatique paramétrable d'un lot dont le certificat manque. |
| **Rappel produit** | Sélection d'un lot suspect, calcul de la généalogie aval jusqu'aux clients livrés, sélection du périmètre à rappeler, génération d'un dossier de rappel figé, notification par le canal si consenti. Journal en ajout seul. |

**Règles de gestion**

- Un dépassement de limite critique sur un point de contrôle critique bloque automatiquement le lot concerné, sans attendre une décision.
- Un lot ne peut pas être libéré tant qu'une non-conformité ouverte le concerne.
- Une décision de libération n'est jamais antidatée : l'horodatage est celui du serveur, et une date d'effet antérieure est refusée.
- Un contrôle dû et non réalisé apparaît en retard et remonte en alerte ; il n'est jamais silencieusement clos par le temps.
- Le dossier de rappel est figé à sa génération : lots, clients, quantités et décisions y sont conservés en l'état, même si les données évoluent ensuite.

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **QUA-1** | La saisie d'une mesure hors limite critique sur un point de contrôle critique bloque le lot dans la même transaction, sans intervention humaine. |
| **QUA-2** | La libération d'un lot concerné par une non-conformité ouverte est refusée, avec un message désignant la non-conformité bloquante. |
| **QUA-3** | Une décision de blocage ou de libération porte l'identité, l'horodatage serveur et un motif ; une tentative d'antidatage est refusée, et toute décision apparaît au journal d'audit. |
| **QUA-4** | À partir d'un lot suspect, la liste des lots finis et des clients livrés impactés est restituée en moins de 5 secondes sur un jeu représentant trois exercices d'activité. |
| **QUA-5** | La généalogie amont d'un lot fini remonte jusqu'aux lots fournisseurs d'origine à travers tous les niveaux de transformation, et son résultat est identique à celui recalculé depuis les mouvements bruts. |
| **QUA-6** | Un dossier de rappel rouvert un an plus tard affiche exactement les mêmes lots, clients, quantités et décisions qu'à sa génération. |
| **QUA-7** | Le journal de rappel n'accepte que des ajouts : aucune voie applicative ne permet de modifier, réordonner ou supprimer un événement enregistré. |
| **QUA-8** | Un lot reçu sans certificat d'analyse valide, sur un article paramétré comme l'exigeant, est bloqué automatiquement à la réception. |
| **QUA-9** | Un contrôle dû et non réalisé à son échéance apparaît en retard dans la liste des contrôles et déclenche une alerte ; il ne disparaît pas avec le temps. |
| **QUA-10** | L'exercice de rappel blanc, exécuté sur un jeu de données de production anonymisées, aboutit à un dossier complet et cohérent, vérifié par le contrôleur qualité du client. |

### 13.5 Module Paie

**Objectif** : un bulletin exact, explicable ligne à ligne, produit sans ressaisie et sans livraison logicielle à chaque changement de barème. Le risque de ce module n'est ni technique ni ergonomique : c'est le recueil des règles réelles de l'entreprise (H17), qui prend systématiquement plus de temps que prévu.

| Écran | Contenu et interactions |
|---|---|
| **Dossier salarié** | Identité, coordonnées, identifiants d'organismes sociaux, situation familiale, coordonnées bancaires ou de paiement, pièces. Historique des contrats et avenants avec dates d'effet. |
| **Contrat** | Type, durée, poste, centre de charge d'imputation, rémunération de base, éléments fixes récurrents, régime horaire. Un avenant crée une version datée, il n'écrase pas. |
| **Absences et congés** | Demande, validation par le responsable sur le moteur de workflow, compteurs de droits acquis et pris, incidence automatique sur le bulletin. |
| **Pointage et heures supplémentaires** | Grille par salarié et par jour, saisie ou import, calcul des heures supplémentaires selon les seuils paramétrés, anomalies signalées avant le calcul. |
| **Rubriques et règles** | Écran de gouvernance du moteur : rubrique, ordre d'évaluation, base de calcul, taux ou montant issu d'un paramètre versionné, condition d'application, imputation comptable et analytique, cumuls alimentés. Simulation sur un salarié témoin avant activation. |
| **Cycle de paie** | Ouverture, collecte des variables, calcul par lots avec avancement, tableau de contrôle des anomalies, verrouillage, publication. Aucun bulletin n'est publié individuellement hors cycle. |
| **Bulletin** | Chaque ligne dépliable sur sa base, son taux, le paramètre appliqué et sa version à la date. Mise à disposition par le canal avec consentement. |
| **Journal, écritures et déclarations** | Journal de paie, écriture comptable agrégée sur le référentiel de la Phase 1, imputation par centre de charge, ordre de virement exportable, états déclaratifs reconstitués et datés. |
| **Prêts et acomptes** | Octroi, échéancier, retenue automatique sur bulletin, solde restant dû. |

**Règles de gestion**

- **Aucun taux, barème, tranche ou plafond n'est écrit dans le code.** Tous proviennent des paramètres versionnés, lus à la date du bulletin. Un test d'intégration continue échoue si une valeur numérique de nature réglementaire apparaît dans le code du moteur.
- Un paramètre non validé par l'expert-comptable est marqué comme tel ; un cycle de paie ne peut pas être publié s'il utilise un paramètre non validé.
- Le bulletin publié est immuable. Une correction produit une régularisation datée et motivée, portée par un cycle ultérieur et visible sur le bulletin correspondant.
- Le cycle est l'unité de publication : les contrôles de cohérence portent sur l'ensemble du cycle, et le verrouillage est global.
- La main-d'œuvre est imputée au centre de charge du contrat, et le coût de production d'un ordre de fabrication reprend cette imputation — c'est le seul point de contact entre la paie et le flux physique.
- Toute consultation d'un montant de rémunération individuel est journalisée (6.1).

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **PAY-1** | Un test d'intégration continue échoue si une valeur de nature réglementaire (taux, tranche, plafond) est trouvée en dur dans le code du moteur de paie. |
| **PAY-2** | Le calcul d'un bulletin utilise la version du paramètre en vigueur à la date du bulletin, et non la version courante ; un recalcul d'un mois antérieur redonne le même résultat après une évolution de barème. |
| **PAY-3** | Un cycle utilisant au moins un paramètre marqué non validé ne peut pas être publié ; l'écran désigne le paramètre concerné. |
| **PAY-4** | Chaque ligne de bulletin est dépliable sur sa base de calcul, son taux, l'identifiant du paramètre appliqué et sa version ; aucune ligne n'est produite sans cette traçabilité. |
| **PAY-5** | L'ajout d'une rubrique nouvelle et sa mise en service ne nécessitent aucune modification de code, vérifié par un scénario complet de bout en bout sur un salarié témoin. |
| **PAY-6** | Un avenant crée une version datée du contrat ; le bulletin d'un mois antérieur reste calculé sur la version en vigueur à cette date. |
| **PAY-7** | Un cycle présentant une variation de net supérieure au seuil paramétré sur un salarié ne peut pas être publié tant que l'anomalie n'est pas visée avec un motif. |
| **PAY-8** | Un bulletin publié refuse toute modification et toute suppression, y compris par appel direct de l'API et y compris pour un administrateur. |
| **PAY-9** | Une correction après publication produit une régularisation datée, motivée, rattachée au bulletin d'origine et visible sur le bulletin du cycle suivant. |
| **PAY-10** | Le journal de paie d'un cycle publié se déverse en une écriture comptable équilibrée, dont la somme des rubriques est égale au total du journal à l'ariary près. |
| **PAY-11** | Un utilisateur sans le rôle Paie n'accède à aucun montant de rémunération individuel, y compris par un rapport, un export, un tableau de bord agrégé ou un outil du copilote ; testé rôle par rôle. |
| **PAY-12** | La validation d'un jeu de bulletins témoins couvrant les cas limites — entrée et sortie en cours de mois, absence, heures supplémentaires, acompte, régularisation — est signée par un expert-comptable OECFM avant mise en production. |

### 13.6 Extension du module Forecast

**Objectif** : tenir la promesse ouverte en Phase 2. Le principe posé alors reste entier : une prévision publie son erreur, et l'ajustement humain est autorisé, tracé et évalué. Il s'applique désormais à la matière et à la charge.

| Écran | Contenu et interactions |
|---|---|
| **Besoins matière** | Développement de la prévision de ventes à travers les nomenclatures, confrontation au stock disponible, aux réservations, aux commandes fournisseur en cours et aux règles de réapprovisionnement. Résultat par article, par période et par dépôt. |
| **Proposition de réapprovisionnement** | Liste de propositions avec quantité, date de commande souhaitable au regard du délai fournisseur, et justification dépliable : d'où vient le besoin, quel stock est pris en compte. Acceptation ou rejet avec motif, transformation en demande d'achat. |
| **Charge d'atelier** | Charge projetée par poste et par période, issue des gammes et des ordres prévus, comparée à la capacité indicative. Signale les périodes de dépassement, sans ordonnancer. |
| **Alertes de couverture et de péremption** | Articles dont la couverture passe sous le stock de sécurité sur l'horizon, et lots dont la date limite arrivera avant leur écoulement prévu. |

| Réf. | Critère d'acceptation (testable) |
|---|---|
| **FOR-11** | Le calcul de besoins s'exécute sur le modèle dimensionnel de la Phase 2 étendu, sans modification des dimensions conformes existantes — vérifié par un test comparant leur structure avant et après. |
| **FOR-12** | Chaque proposition de réapprovisionnement est dépliable sur sa justification complète : besoin d'origine, nomenclature appliquée, stock et en-cours déduits, règle de réapprovisionnement utilisée. |
| **FOR-13** | Une proposition rejetée exige un motif, et le motif est conservé et restituable ; le taux d'acceptation des propositions est mesuré et affiché. |
| **FOR-14** | La charge d'atelier projetée est confrontée au réalisé sur les périodes échues, et son erreur est publiée selon le même protocole de rétrotest que la prévision de ventes. |
| **FOR-15** | Une alerte de péremption est déclenchée lorsque la date limite d'un lot précède sa date d'écoulement prévue, et disparaît lorsque le lot est écoulé ou bloqué. |

**Pourquoi la proposition de réapprovisionnement n'est jamais automatique.** Techniquement, transformer une proposition en commande fournisseur sans intervention est trivial. Fonctionnellement, c'est le moyen le plus sûr de perdre la confiance de l'acheteur : la première commande absurde — parce qu'une nomenclature était fausse, parce qu'un stock n'était pas à jour, parce qu'un délai fournisseur avait changé — suffit à faire désactiver la fonction pour toujours. La proposition est donc toujours soumise à décision, et le taux d'acceptation devient l'indicateur qui dit si le calcul mérite la confiance. C'est le même raisonnement qui a conduit, en Phase 2, à afficher l'erreur de prévision plutôt qu'à la masquer.

## 14. Plan de développement — sprints hebdomadaires

*38 semaines, 8 blocs, 2 vagues, une seule table de mouvement*

La cadence hebdomadaire est maintenue, pour la même raison qu'en Phases 1 et 2 : un agent produit vite, ce qui rend facile de partir loin dans une mauvaise direction, et une revue bornée limite mécaniquement l'ampleur d'un écart. Deux différences importantes avec la Phase 2. La capacité baisse encore, de 4,5 à 4 jours effectifs par semaine, parce que le support couvre désormais deux phases en production. Et le plan comporte une **mise en production intermédiaire au sprint 18**, qui n'est pas un jalon de revue mais une vraie livraison au client.

### 14.1 Ordonnancement et dépendances

****Chaîne de dépendances des blocs et découpage en vagues****

```
   S1→S7      S8→S13    S14→S18  ┃  S19→S24   S25→S28   S29→S33  S34→36 S37→38
 ┌──────────┬──────────┬─────────╂─┬─────────┬─────────┬─────────┬──────┬─────┐
 │ A SOCLE  │ B  STOCK │ C ACHATS┃ │ D PRO-  │ E QUALI-│ F PAIE  │ G FO-│  H  │
 │INVENTAIRE│ ENTREPÔT │  IMPORT ┃ │ DUCTION │ TÉ HACCP│         │RECAST│ MEP │
 └──────────┴──────────┴─────────╂─┴─────────┴─────────┴─────────┴──────┴─────┘
   ◀──────── VAGUE 3A ─────────> ┃ ◀─────────────── VAGUE 3B ───────────────>
                          JALON J2 — MISE EN PRODUCTION 3A
```

****Dépendances croisées à surveiller****

```
A (mouvement + valorisation) ───> B, C, D, E
   Cinq modules écrivent dans la même table. Une erreur de conception du
   mouvement au sprint 3 se répare au sprint 5 ; au sprint 20, elle se répare
   en reprenant quatre modules. D'où sept sprints sans écran métier.
A (S2) ───> G (Forecast)
   La vérification que le modèle dimensionnel de la Phase 2 accueille les faits
   nouveaux SANS reprise est faite au sprint 2, pas au sprint 34. Si elle
   échoue, G est replanifié avant l'engagement de B.
B (stock) ─> C (réception) ─> D (consommation) ─> E (blocage de lot)
   Chaîne physique stricte : on ne reçoit pas dans un stock qui n'existe pas,
   on ne consomme pas ce qu'on n'a pas reçu, on ne bloque pas un lot qui n'a
   pas été produit. Aucune parallélisation possible.
D + E ───> G (besoins matière et charge d'atelier)
   Le calcul de besoins suppose les nomenclatures et les gammes. C'est
   exactement la dépendance annoncée en Phase 2.
F (Paie) ───> indépendant du flux physique
   Seul bloc déplaçable. Il est placé tard parce que son hypothèse la plus
   lourde (H17, recueil des règles réelles) est celle dont le délai est le moins
   maîtrisé par l'éditeur, et parce qu'il ne bloque rien en aval. Son seul point
   de contact — l'imputation de main-d'œuvre au coût de production — est un
   raccordement de fin de bloc, pas une dépendance.
```

**Sept sprints sans écran métier, pour la troisième fois.** Le bloc A ne produit rien que le client puisse apprécier, exactement comme le socle UX en Phase 1 et le socle analytique en Phase 2. La tentation sera de livrer un écran de réception au sprint 3 pour rassurer. Elle est à écarter pour une raison précise : un écran de réception construit avant le moteur de mouvement écrira sa propre logique de stock, et cette logique deviendra la référence par simple antériorité. La contre-mesure est la même qu'en Phase 2 : communiquer autrement pendant ces sept semaines, en montrant le rejeu de valorisation et le contrôle de cohérence, démontrables dès le sprint 4 sur des données réelles.

### 14.2 Bloc A — Socle d'inventaire et cadrage (S1 à S7)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S1** | Cadrage et lignes de base | Inventaire des attributs de gestion manquants sur le référentiel article existant, par tenant. Ligne de base des parcours UC15 à UC24 sur la pratique actuelle (cahier, tableur, ressaisie). Arbitrage de l'incrément de rapports. Plan de mise en service des trois reprises identifiées en 2.5. | 5 | 2 |
| **S2** | Modèle de mouvement et vérification dimensionnelle | Table de mouvement, orientation, natures, partitionnement par exercice, RLS, index. Vérification que le modèle en étoile de la Phase 2 accueille les quatre faits nouveaux sans reprise des dimensions conformes (FOR-11). Vérification de l'exploitabilité du mouvement indicatif POS — lève H12. | 6 | 2,5 |
| **S3** | Unités, lots, emplacements | Unités de mesure et conversions vérifiées, dépôts / zones / emplacements, lot et numéro de série, blocage, réservation. Arbitrage CUMP contre FIFO par lot avec le client — lève H13. c-uom-converter, c-qty-dual. | 5 | 2 |
| **S4** | Moteur de valorisation | CUMP par article, rejeu complet d'un historique, valeur de stock à une date, agrégat matérialisé et contrôle nocturne de cohérence agrégat / recalcul (STK-2, STK-12). Démonstration du rejeu sur données réelles. | 6 | 2,5 |
| **S5** | Inventaire permanent | Écriture de variation de stock sur le référentiel comptable de la Phase 1, paramétrage par famille, rapprochement bloquant stock / comptabilité à la clôture de période. | 5 | 2 |
| **S6** | Bascule du POS et composants terrain | La sortie de caisse devient un mouvement réel, sans reprise du modèle de vente ; test de non-régression complet sur le POS. c-scan-input, c-lot-picker, c-bin-map. | 5 | 2,5 |
| **S7** | Mode dégradé terrain | Extension du protocole hors ligne du POS à l'entrepôt : file de saisie persistante et visible, numérotation préfixée par poste, réconciliation avec arbitrage explicite des conflits. Banc d'essai de coupure — prépare H19. | 4 | 2,5 |

> Fin du bloc A — jalon J1 : le mouvement, la valorisation et le mode dégradé sont démontrables. Point de recalibrage des estimations. Total du bloc : 36 J/H, 16 J-Token.

### 14.3 Bloc B — Stock et entrepôt (S8 à S13)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S8** | Réception et rangement | Écran de réception au scan, lot et date limite, emplacement suggéré, réception partielle et tolérance, étiquettes. Test de coupure sur une réception de trente lignes — lève H19 (STK-9, STK-10). | 6 | 2,5 |
| **S9** | Transfert et transit | Transfert entre emplacements et entre dépôts avec état de transit, mouvement unique à deux emplacements, interruption sans perte (STK-5). | 5 | 2 |
| **S10** | Prélèvement et FEFO | Préparation ordonnée par emplacement, proposition FEFO puis FIFO, dérogation motivée, expédition et bon de livraison rattaché à la commande Phase 1 (STK-3, STK-4). Mesure UC16. | 5 | 2 |
| **S11** | Inventaire | Session tournante et complète, comptage à l'aveugle, gel du périmètre, écarts, seuils par famille, séparation des tâches, régularisation par mouvement (STK-6 à STK-8). Mesure UC17. | 5 | 2 |
| **S12** | Consultation et règles de réapprovisionnement | Stock par article, emplacement et lot avec disponible / réservé / bloqué / transit ; historique ; règles de réapprovisionnement par article et par dépôt. Engagement de la vérification bancaire — prépare H14. | 5 | 2,5 |
| **S13** | Écran magasinier et durcissement | Vue tablette à densité réduite, quatre actions, indicateur de file toujours visible. Campagne de mesure sur les parcours UC15 à UC17, SEQ et temps par tâche. Correction des écarts constatés. | 4 | 2 |

> Fin du bloc B — le stock est juste, mesuré et tenu au scan. Total du bloc : 30 J/H, 13 J-Token.

### 14.4 Bloc C — Achats, import et CREDOC (S14 à S18)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S14** | Demande, consultation, commande | Demande d'achat et circuit d'approbation sur le workflow existant, consultation fournisseur et comparatif, commande avec unité d'achat, devise et date de référence (ACH-1 à ACH-3). Vérification du périmètre douanier — lève H15. | 6 | 2,5 |
| **S15** | Dossier d'import et CREDOC | Dossier conteneur, chronologie, cycle de vie du crédit documentaire en états contrôlés, liasse documentaire, échéances et alertes (ACH-4, ACH-5). Lève H14. | 6 | 2,5 |
| **S16** | Coût débarqué | c-landed-cost : ventilation par clé au choix avec contrôle de somme bloquant, valorisation provisoire puis définitive, reprise de l'écart dans le CUMP (ACH-6, ACH-7, ACH-10). Mesure UC18. | 6 | 2,5 |
| **S17** | Facture et rapprochement | Facture fournisseur, rapprochement à trois voies avec tolérance et blocage, séparation des tâches, écriture comptable (ACH-8, ACH-9). | 5 | 2 |
| **S18** | Durcissement et mise en production 3A | Recette des 22 critères STK et ACH, barrières techniques de la vague 3A, restauration de sauvegarde vérifiée, accompagnement de l'inventaire initial chez le client pilote, bascule. | 3 | 1,5 |

> Fin du bloc C — jalon J2 : mise en production de la vague 3A. Le flux entrant et le stock sont en service réel. Total du bloc : 26 J/H, 11 J-Token.

### 14.5 Bloc D — Production (S19 à S24)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S19** | Nomenclatures | c-bom-tree, développement à plusieurs niveaux avec détection de récursivité, taux de perte, nomenclature de process avec sous-produits, courbe de consommation par taille pour le textile (PRD-1, PRD-2). Diagnostic des nomenclatures réelles — lève H16. | 6 | 2,5 |
| **S20** | Gammes et postes de charge | Opérations, temps de préparation et unitaire, capacité indicative, marquage des opérations sous-traitées. | 5 | 2 |
| **S21** | Ordre de fabrication | États, réservation des composants et libération à la clôture, coût prévu, annulation (PRD-3, PRD-10). | 5 | 2 |
| **S22** | Atelier et déclarations | c-workshop-board sur tablette, déclaration de consommation et de production en trois gestes, création du lot fini attaché aux lots consommés, rebut motivé (PRD-4, PRD-5). Mesure UC19. | 6 | 2,5 |
| **S23** | Sous-traitance de façon | Sortie de matière vers façonnier, emplacement de sous-traitance, suivi de l'en-cours, retour et valorisation de la prestation (PRD-8). | 4 | 2 |
| **S24** | Coût de revient et rendement | Coût réel contre prévu, rendement réel contre théorique avec tolérance, taux de conformité au premier passage calculé et non saisi, écarts commentés (PRD-6, PRD-7, PRD-9). | 5 | 2 |

> Fin du bloc D — jalon J3 : un ordre de fabrication produit un lot tracé et un coût de revient réel. Total du bloc : 31 J/H, 13 J-Token.

### 14.6 Bloc E — Qualité et HACCP (S25 à S28)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S25** | Plans et points de contrôle | Plan par article, étape ou réception, limites critiques, marquage des points de contrôle critiques, fréquence, retard et alerte (QUA-9). c-control-checklist. Lancement du recueil des règles de paie — prépare H17. | 5 | 2 |
| **S26** | Mesure, blocage, libération | Saisie tablette, blocage automatique sur dépassement de limite critique, décision horodatée non antidatable, effet immédiat sur la disponibilité (QUA-1 à QUA-3). Mesure UC20. | 5 | 2,5 |
| **S27** | Non-conformités et certificats | Non-conformité et action corrective sur le workflow existant, blocage de libération tant qu'une non-conformité est ouverte, certificat d'analyse fournisseur et blocage automatique à défaut (QUA-2, QUA-8). | 5 | 2 |
| **S28** | Généalogie et rappel | c-recall-tree, généalogie amont et aval, dossier de rappel figé, journal en ajout seul, notification par le canal. Mesure de performance sur trois exercices et exercice de rappel blanc (QUA-4 à QUA-7, QUA-10). Mesure UC21. | 5 | 2,5 |

> Fin du bloc E — la traçabilité est opposable et l'exercice de rappel blanc est réussi. Total du bloc : 20 J/H, 9 J-Token.

### 14.7 Bloc F — Paie (S29 à S33)

La difficulté de ce bloc n'est pas logicielle : elle est de recueil et de validation. Deux sprints sur cinq portent sur des règles à obtenir du client et à faire valider par un tiers, et c'est ce qui détermine si le module sera juste.

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S29** | Dossier salarié et moteur de rubriques | Salarié, contrat et avenants versionnés, écran de gouvernance des rubriques : ordre, base, condition, imputation, cumuls, simulation sur salarié témoin. Plafond de rubriques fixé et vérifié en CI (PAY-5, PAY-6). | 6 | 2,5 |
| **S30** | Paramètres et calcul | Chargement des barèmes dans les paramètres versionnés, lecture à la date du bulletin, marquage des paramètres non validés, calcul par lots avec avancement (PAY-1 à PAY-3). Recueil des règles réelles en parallèle — H17. | 6 | 2,5 |
| **S31** | Absences, pointage, cycle | c-timesheet-grid, absences et compteurs, heures supplémentaires, cycle avec contrôles de cohérence et anomalies bloquantes à la publication (PAY-7). Vérification des formats déclaratifs — lève H18. | 6 | 2 |
| **S32** | Bulletin, régularisation, écritures | c-payslip-viewer avec traçabilité de chaque ligne vers son paramètre, immutabilité du bulletin publié, mécanisme de régularisation, journal et écriture comptable, imputation par centre de charge (PAY-4, PAY-8 à PAY-10). Mesures UC22 et UC23. | 6 | 2,5 |
| **S33** | Déclarations, cloisonnement, validation | États déclaratifs datés, ordre de virement exportable, prêts et acomptes. Cloisonnement complet du module testé rôle par rôle (PAY-11). Revue du jeu de bulletins témoins par l'expert-comptable (PAY-12). Renseignement des durées de rétention. | 4 | 1,5 |

> Fin du bloc F — jalon J4 : un cycle de paie complet est produit, contrôlé, publié et validé par un tiers. Total du bloc : 28 J/H, 11 J-Token.

### 14.8 Bloc G — Extension Forecast (S34 à S36)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S34** | Besoins matière | Développement de la prévision de ventes à travers les nomenclatures, confrontation au stock, aux réservations et aux commandes en cours, calcul par famille dans la file longue (FOR-11). | 4 | 2 |
| **S35** | Proposition et justification | Proposition de réapprovisionnement avec justification dépliable, acceptation ou rejet motivé, transformation en demande d'achat, taux d'acceptation mesuré (FOR-12, FOR-13). Mesure UC24. | 4 | 1,5 |
| **S36** | Charge d'atelier et alertes | Charge projetée par poste avec erreur publiée par rétrotest, alertes de couverture et de péremption (FOR-14, FOR-15). | 4 | 1,5 |

> Fin du bloc G — la promesse ouverte en Phase 2 est tenue et son erreur est publiée. Total du bloc : 12 J/H, 5 J-Token.

### 14.9 Bloc H — Durcissement et mise en production (S37 et S38)

| S | Semaine — objectif | Définition de fin (livré et démontrable) | J/H | J-Tok |
|---|---|---|---|---|
| **S37** | Recette et accessibilité | Les 59 critères passent en intégration continue. Budget d'accessibilité des douze composants nouveaux. Traduction prioritaire des libellés terrain. Campagne de mesure finale UC15 à UC24. | 3 | 1 |
| **S38** | Mise en production 3B | Quatorze barrières techniques au vert, restauration vérifiée avec reconstitution d'une généalogie, registre des traitements étendu, conditions de la section 17.4 réunies, bascule. | 2 | 1 |

### 14.10 Répartition du travail entre l'humain et l'assistant

La règle des Phases 1 et 2 est inchangée : la conception précède la génération. Elle se durcit sur trois parties de cette phase, où une génération lancée sans conception écrite produit du code plausible et faux.

| Nature du travail | Qui le fait | Pourquoi |
|---|---|---|
| **Modèle de mouvement, orientation, natures, règles de valorisation** | Humain seul, avant toute génération | Une erreur ici est irréparable après le sprint 10. C'est le cœur du domaine, et c'est exactement le type de conception où un assistant produit une solution cohérente mais inadaptée au flux réel. |
| **Règles de paie réelles de l'entreprise, mapping vers les rubriques** | Humain seul, avec le client et l'expert-comptable | Ce travail n'est ni délégable ni devinable : il s'agit d'usages d'entreprise, pas de logique. C'est la charge de supervision la plus élevée de la phase (H17). |
| **Protocole de réconciliation hors ligne étendu** | Humain seul pour la conception, assistant pour l'implémentation | Même raisonnement qu'en Phase 1 pour le POS : un doublon ou une perte de saisie ne se rattrape pas. |
| **Écrans dérivés du moteur de vues, formulaires, listes, rapports** | Assistant, revue humaine légère | Répétitif et bien cadré une fois le socle en place. C'est là que se concentre le gain. |
| **Critères d'acceptation traduits en tests** | Assistant, à partir de la section 13 | Les 59 critères sont écrits pour être automatisables sans reformulation. C'est la raison d'être de leur formulation. |

## 15. Estimation détaillée

*Une capacité qui baisse encore, un gain assisté qui baisse aussi*

### 15.1 Hypothèses de l'estimation

- Un seul développeur, maîtrisant le socle qu'il a construit sur deux phases, mais découvrant la gestion de stock valorisée et la paie — deux domaines où la difficulté est métier et non technique.
- **4 jours de travail effectif par semaine**, contre 4,5 en Phase 2 et 5 en Phase 1 : le support couvre désormais deux phases en production, sur un nombre de clients plus élevé.
- Les lots transverses (environnement, tests, intégration continue, documentation, gestion de projet) sont inclus dans les chiffres par sprint et non ajoutés ensuite.
- Les travaux de mise en service décrits en 2.5 — renseignement des attributs article, inventaire physique initial, saisie des nomenclatures manquantes — ne sont pas dans le chiffrage de développement. Ce sont des prestations à chiffrer à part.
- Le recueil des règles de paie et leur validation par l'expert-comptable ne sont pas du développement non plus, mais ils consomment du temps de supervision : ils sont comptés dans les 12 J/H de supervision du bloc F.
- Les ratios entre effort classique et effort assisté sont calibrés sur les mesures réelles des Phases 1 et 2. Le profil de tâches de la Phase 3 comporte davantage de conception de domaine et de règles métier, ce qui réduit le gain. Le sprint 7 sert de point de recalibrage.

### 15.2 Synthèse par bloc

| Bloc | Sprints | J/H — voie classique | J-Token — génération | J/H — supervision humaine |
|---|---|---|---|---|
| **A — Socle d'inventaire et cadrage** | S1–S7 | 36 | 16 | 14 |
| **B — Stock et entrepôt** | S8–S13 | 30 | 13 | 11 |
| **C — Achats, import et CREDOC** | S14–S18 | 26 | 11 | 10 |
| **D — Production** | S19–S24 | 31 | 13 | 12 |
| **E — Qualité et HACCP** | S25–S28 | 20 | 9 | 8 |
| **F — Paie** | S29–S33 | 28 | 11 | 12 |
| **G — Extension Forecast** | S34–S36 | 12 | 5 | 4 |
| **H — Durcissement et mise en production** | S37–S38 | 5 | 2 | 1 |
| **Total Phase 3** | **38** | **188** | **80** | **72** |

Le bloc F est le seul dont la supervision humaine (12 J/H) dépasse la génération (11 J-Token). Ce n'est pas une anomalie de calcul : c'est la traduction chiffrée de H17. Écrire un moteur de rubriques est un travail cadré ; établir quelles rubriques s'appliquent, avec quelles bases et quelles conditions, est un travail d'entretien, de lecture de textes et de validation par un tiers, qu'aucun assistant ne peut porter.

### 15.3 Comparaison avec les Phases 1 et 2

| Indicateur | Phase 1 | Phase 2 | Phase 3 | Lecture |
|---|---|---|---|---|
| **Sprints** | 29 | 22 | 38 | Périmètre le plus large des trois : cinq modules et un socle de domaine. |
| **J/H par sprint** | 5,9 | 6,0 | 4,9 | La baisse suit celle de la capacité hebdomadaire, pas une baisse d'intensité. |
| **Rapport J/H ÷ J-Token** | 2,30 | 2,40 | 2,35 | Stable. Le gain sur les écrans dérivés compense la perte sur la conception de domaine et les règles métier. |
| **Supervision ÷ J-Token** | 0,81 | 0,83 | 0,90 | En hausse nette : la relecture humaine domine sur la valorisation, la traçabilité et la paie. |
| **Nouveaux composants UI** | ~20 | 9 | 12 | Remontée modérée : les écrans terrain n'ont pas d'équivalent dans le socle existant. |
| **Capacité hebdomadaire retenue** | 5 j | 4,5 j | 4 j | Support cumulé de trois phases à terme. C'est la tendance la plus préoccupante du projet. |

**La capacité baisse de 20 % en deux phases, et rien n'indique que cela s'arrête.** C'est l'enseignement le plus utile de cette comparaison, et il ne concerne pas la Phase 3 mais ce qui la suit. À capacité constante de décroissance, une Phase 4 se ferait à 3,5 jours effectifs. Trois leviers existent, et ils doivent être arbitrés avant la fin de la vague 3A, pas après : industrialiser le support (documentation, réponses types, autoformation client), le déléguer à une ressource dédiée même à temps partiel, ou accepter que le produit entre en régime de maintenance après la Phase 3. Ne pas choisir revient à choisir le troisième.

### 15.4 Trois scénarios

| Scénario | J/H classique | J-Token | Supervision | Durée | Ce qui le déclenche |
|---|---|---|---|---|---|
| **Optimiste** | 152 | 65 | 57 | 31 sem. | Le mouvement indicatif du POS est exploitable tel quel (H12) ; le CUMP suffit et le FIFO par lot n'est pas développé (H13) ; les nomenclatures clients sont exploitables (H16) ; les règles de paie sont recueillies et validées sans itération longue (H17). |
| **Réaliste** | 188 | 80 | 72 | 38 sem. | Scénario de référence du plan de la section 14. |
| **Pessimiste** | 262 | 112 | 104 | 54 sem. | La reprise de l'historique de stock impose un inventaire physique complet chez chaque client avant bascule ; le FIFO par lot est exigé en plus du CUMP ; les nomenclatures doivent être saisies avant tout calcul de besoins ; le recueil des règles de paie exige plusieurs itérations et une double validation ; la performance de généalogie impose une table de correspondance matérialisée. |

### 15.5 Marges appliquées par type de tâche

| Type de tâche | Marge | Justification |
|---|---|---|
| **Écrans dérivés du socle, listes, formulaires, dossiers** | +10 à 20 % | Répétitif et bien cadré. Le moteur de vues couvre l'essentiel. |
| **Écrans terrain, scan, mode dégradé** | +30 à 50 % | La difficulté est le comportement réel du matériel et du réseau, qui ne se découvre qu'à l'usage. |
| **Modèle de mouvement, valorisation, inventaire permanent** | +50 à 100 % | Forte incertitude : dépend de la qualité de l'existant (H12) et d'un arbitrage client non tranché (H13). Se découvre en modélisant. |
| **Nomenclatures, calcul de besoins, coût de revient** | +50 à 100 % | Dépend de la richesse et de la fiabilité des nomenclatures réelles (H16), inconnues à la rédaction. |
| **Généalogie et performance de traçabilité** | +50 à 100 % | Le comportement du parcours de graphe sur des données réelles très composées n'est pas prévisible sans mesure. |
| **Moteur et règles de paie** | +50 à 100 % | Deux inconnues externes : les règles réelles de l'entreprise (H17) et les formats déclaratifs (H18), toutes deux hors du contrôle de l'éditeur. |

## 16. Risques et plan de mitigation

*Numérotation propre à la Phase 3*

| Réf. | Risque | Impact | Prob. | Mitigation et signal d'alerte |
|---|---|---|---|---|
| **P3-R1** | Le stock informatique diverge du stock physique dès les premières semaines d'exploitation, et les utilisateurs recommencent à tenir un cahier en parallèle. | Critique | Élevée | Inventaire physique initial daté et validé comme condition d'entrée en production (12.4, 17.4) ; interdiction du stock négatif (STK-1) ; contrôle nocturne agrégat / recalcul (STK-2) ; inventaire tournant systématique dès la bascule. Signal : deux écarts inexpliqués au-delà du seuil sur une même zone → arrêt des livraisons et audit du parcours de saisie avant de continuer. |
| **P3-R2** | Le mode dégradé terrain perd ou duplique des saisies. Une réception disparue est un litige fournisseur. | Critique | Moyenne | Protocole du POS réutilisé et non réinventé (H19) ; conception humaine avant génération (14.10) ; tests de coupure et de reprise automatisés (STK-9) ; file visible pour l'utilisateur. Signal : un seul écart non expliqué en recette → le sprint 8 est prolongé plutôt que le bloc B engagé. |
| **P3-R3** | Le volume de mouvements dégrade la base, déjà partagée entre charge transactionnelle et charge analytique de la Phase 2. | Majeur | Moyenne | Partitionnement par exercice dès la conception ; agrégat matérialisé ; index ciblés ; mesure de généalogie sur trois exercices en recette (QUA-4) ; repli identifié en Phase 2 sur un moteur analytique dédié. Signal : généalogie au-delà de 5 s, ou fenêtre nocturne dépassée deux nuits de suite. |
| **P3-R4** | Les barèmes ou les règles de paie sont obtenus tard, incomplets, ou validés après le sprint 33. | Critique | Élevée | Recueil engagé au sprint 25, quatre sprints avant le besoin ; paramètres marqués non validés bloquant la publication (PAY-3) ; jeu de bulletins témoins soumis à l'expert-comptable (PAY-12). Signal : règles non recueillies au sprint 29 → le bloc F est décalé après le bloc G, ce que son indépendance permet. |
| **P3-R5** | Un bulletin faux est remis à un salarié, ou une rémunération individuelle est vue par une personne non habilitée. | Critique | Moyenne | Contrôles de cohérence bloquants avant publication (PAY-7) ; immutabilité et régularisation (PAY-8, PAY-9) ; cloisonnement testé rôle par rôle (PAY-11) ; second facteur obligatoire ; journalisation des consultations. Signal : une seule consultation non habilitée détectée → revue complète de la matrice de rôles. |
| **P3-R6** | La traçabilité se révèle incomplète le jour d'un rappel réel : un maillon manque, ou la généalogie ne remonte pas jusqu'au fournisseur. | Critique | Moyenne | Généalogie calculée depuis les mouvements et jamais entretenue en parallèle (5.2) ; interdiction de supprimer un mouvement (6.2) ; exercice de rappel blanc obligatoire avant mise en production (QUA-10). Signal : échec ou résultat partiel de l'exercice blanc → la vague 3B ne passe pas en production. |
| **P3-R7** | Les nomenclatures réelles sont trop pauvres pour alimenter un calcul de besoins, et le bloc G livre une fonction inexploitable. | Majeur | Élevée | Diagnostic au sprint 19 (H16), avant l'engagement du bloc D et bien avant G ; saisie des nomenclatures inscrite comme prestation de mise en service, à la charge du client (2.5). Signal : moins de la moitié du portefeuille couvert au sprint 19 → le bloc G est réduit à la charge d'atelier et aux alertes. |
| **P3-R8** | Le client attend une automatisation des échanges avec la banque ou la douane, non livrable (H14, H15). | Majeur | Élevée | Périmètre écrit en 2.5 et à reprendre tel quel dans l'offre commerciale. Ce risque se traite au contrat, pas en développement, exactement comme la prévision d'approvisionnement en Phase 2. |
| **P3-R9** | Surcharge du développeur solo : le support de deux phases en production absorbe le temps de développement, et le plan glisse sprint après sprint. | Majeur | Élevée | Estimation bâtie sur 4 jours effectifs et non 5 ; découpage en deux vagues avec livraison intermédiaire ; bloc F déplaçable. Signal : deux sprints consécutifs incomplets → réduction du périmètre de la vague 3B, en commençant par la sous-traitance de façon et les alertes, plutôt que prolongation indéfinie du calendrier. |
| **P3-R10** | Le code produit par l'assistant est plausible mais inadapté sur le modèle de mouvement ou sur la valorisation, et l'écart n'est découvert qu'à l'usage. | Majeur | Moyenne | Conception humaine écrite avant toute génération sur ces parties (14.10) ; critères d'acceptation écrits avant l'implémentation ; rejeu complet de valorisation démontré au sprint 4 sur données réelles. Signal : une divergence entre le rejeu et l'agrégat qui n'est pas expliquée en une journée → arrêt du bloc et revue de conception. |

## 17. Critères de recette et métriques de succès

*Un module de flux physique se juge à la justesse de ce qu'il affiche, et à l'usage qu'en fait le terrain*

### 17.1 Recette fonctionnelle

La recette est constituée des critères numérotés de la section 13 : 12 critères Stock, 10 critères Achats et import, 10 critères Production, 10 critères Qualité, 12 critères Paie et 5 critères Forecast, soit **59 critères**, tous automatisés. La **vague 3A** est reçue lorsque les 22 critères STK et ACH passent ; la **Phase 3** est reçue lorsque l'intégralité passe, sans exception tolérée.

### 17.2 Recette technique — barrières bloquantes

| Barrière | Vague | Vérification automatisée |
|---|---|---|
| **Budgets d'architecture** | 3A et 3B | Modèles ≤ 380, endpoints ≤ 1 060, écrans ≤ 245, écrans legacy = 0, rapports ≤ plafond, rubriques de paie ≤ plafond. |
| **Intégrité du mouvement** | 3A | Aucun chemin applicatif ne permet de supprimer ou de modifier un mouvement ; une annulation produit un mouvement inverse référencé. |
| **Cohérence stock** | 3A | Recalcul complet depuis les mouvements égal à l'agrégat sur trois exercices ; divergence introduite volontairement détectée par le contrôle nocturne. |
| **Cohérence stock / comptabilité** | 3A | Valeur de stock à une date égale au solde du compte de stock à l'ariary près ; la clôture est refusée en cas d'écart non expliqué. |
| **Complétude du coût débarqué** | 3A | Aucune réception d'import n'est valorisée définitivement avec une ventilation incomplète. |
| **Robustesse hors ligne** | 3A | Coupure et reprise sur réception, transfert, inventaire et déclaration d'atelier : aucun doublon, aucune perte, dates d'effet préservées. |
| **Séparation des tâches** | 3A | Le compteur ne valide pas son écart au-delà du seuil ; le réceptionnaire ne valide pas la facture. Tentatives refusées et journalisées. |
| **Isolation multi-tenant** | 3A et 3B | Rôle applicatif ni superutilisateur ni exempté de RLS ; policies actives sur toutes les tables nouvelles, faits analytiques et tables de paie compris. |
| **Performance de traçabilité** | 3B | Généalogie amont et aval sous 5 secondes sur un jeu de trois exercices ; résultat identique au recalcul brut. |
| **Immutabilité de la preuve** | 3B | Bulletin publié, dossier de rappel et écart d'inventaire validé refusent toute modification, y compris par l'API et pour un administrateur. |
| **Absence de barème en dur** | 3B | Aucune valeur de nature réglementaire dans le code du moteur de paie ; aucun cycle publiable avec un paramètre non validé. |
| **Cloisonnement de la paie** | 3B | Aucun rôle hors Paie n'accède à un montant individuel par écran, rapport, export, agrégat ou outil IA ; testé rôle par rôle. |
| **Confinement du copilote** | 3B | Aucun outil déclaré ne touche une table de paie ni ne retourne une généalogie ; aucun outil d'écriture n'existe. |
| **Sauvegarde** | 3A et 3B | Restauration réelle testée dans les 30 jours, avec reconstitution vérifiée d'une généalogie de lot et contrôle du chiffrement des données de paie. |

### 17.3 Métriques de succès

Les métriques d'expérience des Phases 1 et 2 restent applicables sur les parcours UC15 à UC24. La Phase 3 y ajoute des métriques de justesse physique et d'usage terrain, parce qu'un module de stock peut passer tous ses critères et rester contourné par un cahier.

| Métrique | Protocole | Cible Phase 3 | Seuil de rattrapage |
|---|---|---|---|
| **Justesse du stock** | Écart d'inventaire tournant, en valeur absolue rapportée au stock compté, par famille. | Sous le seuil défini par famille au sprint 1 | Deux zones au-dessus du seuil → audit du parcours de saisie |
| **Adoption du scan** | Part des mouvements saisis au scan sur le total des mouvements terrain. | ≥ 80 % | < 50 % → revue de conception des écrans terrain |
| **Fiabilité du mode dégradé** | Saisies perdues ou dupliquées rapportées au total des saisies hors ligne. | Zéro | Une seule occurrence → incident majeur |
| **Traçabilité** | Temps de restitution de la généalogie aval sur un cas réel, et exhaustivité vérifiée par le contrôleur qualité. | < 5 s, exhaustivité totale | Résultat partiel → mise en production 3B suspendue |
| **Justesse de la paie** | Bulletins contestés et corrigés par régularisation, rapportés au nombre de bulletins émis. | < 1 % | > 3 % → revue du paramétrage avec l'expert-comptable |
| **Utilité de la proposition de réapprovisionnement** | Part des propositions acceptées, et motifs des rejets. | ≥ 60 % acceptées | < 30 % → revue des règles et des nomenclatures avant d'ajouter des fonctions |
| **SEQ terrain** | Facilité perçue sur les parcours UC15 à UC19, mesurée en situation réelle et non en salle. | ≥ 6 sur 7 | < 5 → revue de conception |
| **SUS** | Même protocole que les Phases 1 et 2, sur les parcours UC15 à UC24. | ≥ 80 | < 68 → revue de conception |

**Pourquoi l'adoption du scan figure parmi les critères.** C'est le meilleur indicateur avancé de la justesse du stock, et il se mesure sans attendre l'inventaire. Un magasinier qui scanne saisit au moment du geste ; un magasinier qui saisit au clavier le fait plus tard, souvent en fin de journée et de mémoire. La part de mouvements scannés dit donc, avant tout écart constaté, si le stock va rester juste. Elle est mesurée dès la mise en production de la vague 3A, alors qu'il est encore temps de corriger les écrans.

### 17.4 Conditions de mise en production

**Vague 3A — au sprint 18**

1. Les 22 critères STK et ACH passent en intégration continue.
2. Les huit barrières techniques marquées 3A sont au vert.
3. **Un inventaire physique complet et daté a été réalisé par dépôt**, sa valorisation d'entrée justifiée et validée par le comptable du client, et figée. Sans cette condition, la bascule est refusée : le CUMP ne se corrige pas rétroactivement.
4. Les attributs de gestion sont renseignés sur 100 % des articles à activer, et les articles non renseignés sont explicitement exclus du périmètre de bascule.
5. La bascule de la sortie POS en mouvement réel est vérifiée sans régression sur un cycle de caisse complet.
6. Une restauration de sauvegarde a été réalisée et vérifiée, tables de mouvement comprises.

**Vague 3B — au sprint 38**

1. Les 59 critères de la section 13 passent en intégration continue.
2. Les quatorze barrières techniques de la section 17.2 sont au vert.
3. L'exercice de rappel blanc est réussi et validé par le contrôleur qualité du client.
4. **Le jeu de bulletins témoins est validé par écrit par un expert-comptable membre de l'OECFM**, et aucun paramètre de paie n'est en état non validé.
5. Les durées de rétention sont renseignées, validées et actives ; le registre des traitements est étendu à la paie et à la traçabilité.
6. Le score SUS est maintenu au niveau des phases précédentes et le SEQ terrain atteint sa cible sur les parcours UC15 à UC19.
7. Une restauration de sauvegarde a été réalisée avec reconstitution vérifiée d'une généalogie de lot et contrôle du chiffrement des données de paie.

## 18. Annexes

*Glossaire, références et suites immédiates*

### 18.1 Glossaire — termes propres à la Phase 3

Les termes définis dans les glossaires des Phases 1 et 2 (PCG 2005, OECFM, IRSA, CNaPS, OSTIE, FMFP, SME, RLS, chatter, launchpad, Jour-Token, SUS, SEQ, FEFO, CREDOC, POS…) ne sont pas répétés ici.

| Terme | Définition |
|---|---|
| **Mouvement de stock** | Enregistrement immuable et orienté de toute variation de quantité, rattaché à sa pièce d'origine. Unique source de vérité du stock dans WideHalo. |
| **CUMP** | Coût unitaire moyen pondéré. Méthode de valorisation recalculée à chaque entrée à partir du stock et de la valeur antérieurs. Méthode unique livrée en Phase 3. |
| **Inventaire permanent** | Tenue comptable dans laquelle chaque mouvement de stock produit ou prépare une écriture, par opposition à l'inventaire intermittent constaté en fin de période. |
| **Coût débarqué (landed cost)** | Coût d'un article importé incluant, outre son prix d'achat converti, le fret, l'assurance, les droits et taxes, le transit et la manutention, ventilés sur les lignes de réception. |
| **Incoterm** | Terme du commerce international définissant la répartition des frais et des risques entre vendeur et acheteur. Porté par le dossier d'import ; conditionne quels coûts entrent dans le coût débarqué. |
| **Liasse documentaire** | Ensemble des documents exigés au règlement d'un crédit documentaire (transport, facture, certificats). Sa conformité conditionne le paiement. |
| **Généalogie de lot** | Reconstitution, dans les deux sens, de la chaîne des lots ayant contribué à un lot donné (amont) et de ceux qui en découlent jusqu'aux clients livrés (aval). Calculée depuis les mouvements. |
| **Traçabilité amont / aval** | Capacité à identifier d'où vient un produit et où il est allé, à un niveau en arrière et un niveau en avant. Exigence courante des marchés d'exportation agroalimentaires. |
| **HACCP** | Méthode de maîtrise des dangers sanitaires reposant sur l'identification de points de contrôle critiques et de leurs limites critiques. |
| **Point de contrôle critique** | Étape à laquelle une mesure de maîtrise est indispensable et où un dépassement de limite critique impose une action immédiate. Dans WideHalo, il déclenche un blocage automatique de lot. |
| **DLC / DLUO** | Date limite de consommation et date limite d'utilisation optimale. Portées par le lot ; fondent la règle FEFO et les alertes de péremption. |
| **Nomenclature (BOM)** | Liste structurée des composants et quantités nécessaires à la fabrication d'un article. La variante « de process » ajoute sous-produits, coproduits et rendement. |
| **Gamme** | Suite ordonnée des opérations de fabrication, avec leur poste de charge et leurs temps. Fonde la projection de charge et l'imputation de main-d'œuvre. |
| **Sous-traitance de façon (CMT)** | Confection à façon : le donneur d'ordre fournit la matière, le façonnier fournit la main-d'œuvre. La matière reste au stock du donneur d'ordre. |
| **Taux de conformité au premier passage** | Part de la production conforme sans reprise ni retouche. Calculée depuis les déclarations réelles, jamais saisie. |
| **Rapprochement à trois voies** | Contrôle croisé entre commande, réception et facture fournisseur avant règlement, avec tolérance paramétrée. |
| **Rubrique de paie** | Élément élémentaire d'un bulletin (gain, retenue, cotisation, information), défini par un ordre d'évaluation, une base, un taux ou un montant issu d'un paramètre versionné, et une condition d'application. |
| **Régularisation** | Correction d'un bulletin déjà publié, portée par un cycle ultérieur sous forme de ligne datée et motivée. Seul mécanisme de correction admis. |
| **Réservation** | Engagement d'une quantité en stock au profit d'une commande, d'un ordre ou d'une préparation. N'est pas un mouvement et n'a aucun effet comptable. |
| **Vague 3A / 3B** | Découpage de la Phase 3 en deux livraisons successives, avec mise en production intermédiaire au sprint 18. |

### 18.2 Documents de référence

- **Cahier des charges WideHalo v3 — Phase 1** : socle d'expérience, CRM, Sales, Accounting (PCG 2005), POS, Simulation financière, Patronnage, IA. Document prérequis ; ses décisions d'architecture ne sont pas rediscutées ici.
- **Cahier des charges WideHalo v3 — Phase 2** : Business Intelligence, Forecast, Strategy, WhatsApp. Document prérequis ; le modèle dimensionnel et le moteur de prévision qu'il livre sont les points d'accroche de la Phase 3.
- INVENTAIRE_EXISTANT.md — produit au sprint 1 de la Phase 1 ; reste le point de vérité sur l'existant.
- **Dictionnaire d'indicateurs** — livrable vivant de la Phase 2. Les indicateurs de stock, de production et de coût de revient y sont déclarés avant tout affichage.
- **Inventaire des attributs de gestion article** — à produire au sprint 1 de la Phase 3. Conditionne le périmètre de bascule de la vague 3A.
- **Recueil des règles de paie de l'entreprise** — à produire des sprints 25 à 29, avec le client. Document de référence métier du bloc F, au même titre que le dictionnaire d'indicateurs l'était pour la Phase 2 (H17).
- **Barèmes et paramètres réglementaires en vigueur** — à obtenir et à faire valider par l'expert-comptable OECFM. Aucune valeur n'est reprise dans le présent document, délibérément.
- **Procédure de rappel du client** — à obtenir avant le sprint 28 ; conditionne le déroulement de l'exercice de rappel blanc.
- **Durées légales de conservation applicables** — à établir avec l'expert-comptable au sprint 33 ; non vérifiées à la rédaction et volontairement non écrites ici (8.2).

### 18.3 Suites immédiates

| Action | Échéance | Pourquoi elle passe avant le développement |
|---|---|---|
| **Vérifier que les Phases 1 et 2 sont stabilisées** | Avant le sprint 1 | Un module de flux physique construit sur un référentiel article instable produit des mouvements faux, et un mouvement faux ne se corrige pas : il se compense par un autre mouvement, visible à l'inventaire. |
| **Inventorier les attributs de gestion manquants sur le référentiel article** | Sprint 1 | Détermine le périmètre réel de la bascule de la vague 3A et le volume de travail de mise en service à chiffrer au client. |
| **Trancher CUMP contre FIFO par lot avec le client** | Sprint 3 au plus tard | L'arbitrage conditionne la conception de la couche de valorisation (H13). Le prendre après le sprint 5 signifierait reprendre le moteur. |
| **Planifier et chiffrer l'inventaire physique initial** | Avant le sprint 10 | C'est une opération lourde chez le client, à caler dans son calendrier d'activité. La découvrir au sprint 17 rendrait la mise en production de la vague 3A impossible à la date prévue. |
| **Engager le recueil des règles de paie** | Sprint 25 | Le délai n'est pas maîtrisé par l'éditeur (H17) et c'est le seul travail de la phase qui ne peut être ni délégué à l'assistant ni décidé par l'éditeur. Quatre sprints d'avance sur le besoin. |
| **Prendre contact avec l'expert-comptable OECFM** | Avant le sprint 29 | Sa disponibilité conditionne la mise en production de la vague 3B, comme elle conditionnait celle de la Phase 1. |
| **Reprendre les exclusions de la section 2.5 dans l'offre commerciale** | Avant toute proposition | Ordonnancement, WMS, interfaces bancaires et douanières, exécution des virements : quatre attentes probables du client, quatre risques de litige s'ils ne sont pas écrits (P3-R8). |
| **Arbitrer la question du support** | Avant la fin de la vague 3A | La capacité hebdomadaire a baissé de 20 % en deux phases (15.3). Le levier — industrialiser, déléguer ou passer en maintenance — doit être choisi tant qu'il reste une vague à livrer. |

> Fin du cahier des charges WideHalo v3 — Phase 3. Ce document suppose les Phases 1 et 2 livrées et n'en respécifie aucune décision. Les 59 critères d'acceptation de la section 13 sont écrits pour être traduits en tests, et le plan de la section 14 pour être suivi sprint par sprint. Avec la Phase 3, la trajectoire produit engagée en Phase 1 est refermée : ce qui suivra — localisation OHADA, consolidation, ressources humaines élargies — devra se construire par paramétrage des moteurs existants plutôt que par ajout d'entités, sous peine de rendre la base ingérable par une seule personne.
