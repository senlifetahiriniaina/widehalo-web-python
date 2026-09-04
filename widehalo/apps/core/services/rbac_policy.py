"""Politique RBAC N2 (objet-type) par role, au-dessus de
`apps.core.services.permissions.require_permission()`.

**Contexte** : `require_permission()` et les 11 roles (`load_roles`) existent
depuis le Lot 1 (etape 5), mais n'ont jamais ete effectivement rattaches a
un seul endpoint API des modules metier — decouvert lors de la verification
des 14 couches du CDC (§8, T6, matrice RBAC). Ce module comble ce trou en
definissant explicitement quelles permissions Django (auto-generees
`view_<model>`/`add_<model>`/`change_<model>` pour chaque modele, plus les
permissions personnalisees deja declarees comme `accounting.validate_accmove`)
chaque role recoit.

**Granularite retenue (simplification assumee)** : par app plutot que par
modele individuel — un role a acces view/add/change a TOUS les modeles d'une
app metier donnee, ou aucun. Une matrice fine par modele (ex. `magasinier`
peut modifier `MrpOrderComponent` mais pas `MrpBom`) demanderait une analyse
metier modele par modele qui n'a pas encore ete faite avec le commanditaire
et qui multiplierait le nombre de regles a maintenir avant meme que les
modules `purchase`/`stocks`/`presence`/`paie` (dont dependent plusieurs de
ces roles) existent. Ce compromis reste un progres net : il remplace
« n'importe quel utilisateur authentifie peut tout faire partout » (l'etat
constate) par une frontiere par role et par module, alignee sur les
descriptions de role du cahier des charges. A affiner (permissions par
modele, scopes N3 supplementaires) au fur et a mesure que les modules
restants du Lot 2 sont construits.

`chat` est deliberement EXCLU de cette politique : c'est une messagerie
interne transversale, pas une donnee metier sensible — tout utilisateur
authentifie y a acces (seule l'appartenance au canal, deja verifiee cote
service, protege son contenu)."""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# {role_code: {app_label: {actions}}} — actions parmi "view"/"add"/"change".
# "delete" est volontairement absent : toutes les entites du projet
# utilisent le soft-delete applicatif (`is_active`/`archived_at`), jamais
# une suppression SQL DELETE exposee via l'API.
ROLE_APP_PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "admin": {
        "accounting": {"view", "add", "change"},
        "crm": {"view", "add", "change"},
        "mrp": {"view", "add", "change"},
        "patronage": {"view", "add", "change"},
        "partners": {"view", "add", "change"},
        "catalog": {"view", "add", "change"},
        "sales": {"view", "add", "change"},
        "purchase": {"view", "add", "change"},
        "stocks": {"view", "add", "change"},
        "logistics": {"view", "add", "change"},
        "presence": {"view", "add", "change"},
        # `strategy` : **limite assumee et disclosee** — le chantier
        # budget/revue/risques (cahier Phase 2 §13.3) classe budget non
        # publie/objectifs/cartographie des risques en donnee "Sensible"
        # (§8.2, "acces restreint aux roles de direction et de controle"),
        # mais la granularite de ce registre reste PAR APP (cf. commentaire
        # de tete du fichier) : `StgBudget`/`StgReviewPack`/`StgRisk`
        # heritent donc du meme acces {view,add,change} que le reste du
        # module `strategy` pour TOUS les roles ci-dessous, pas seulement
        # direction/controle — memes discipline et limite deja assumees
        # ailleurs dans ce registre (granularite par modele non couverte,
        # cf. docstring de tete). A restreindre via un scope N3/une
        # permission personnalisee dediee si un besoin reel de cloisonnement
        # plus strict est exprime.
        "strategy": {"view", "add", "change"},
        # §5.11 reporting : catalogue/generation pour tous les roles
        # (le filtrage reel par rapport passe par `RegisteredReport.
        # permission`, deja porte par le module cible — ex. un rapport
        # `accounting` reste invisible a qui n'a pas `accounting.view_*`) ;
        # "change" (gestion des planifications RPT-7) reserve a
        # admin/direction, pilotage transverse comme le reste de la matrice.
        "reporting": {"view", "add", "change"},
        # `financing` (FIN1-FIN4, cf. plan) : un dossier de financement
        # bancaire n'est PAS une operation courante (pas un role "domaine
        # cible" comme `purchase`/`acheteur`) — RBAC scope explicitement a
        # `admin`/`direction`/`comptable` uniquement (cf. `module.py` et
        # docstring de `services/reports_registration.py`), aucun autre
        # role de la matrice ne recoit `financing` ci-dessous.
        "financing": {"view", "add", "change"},
        # `automation` (Studio de workflow visuel, cf. plan) : un flux
        # d'automatisation est un mecanisme puissant (declenche des
        # notifications/actions metier sans intervention humaine directe),
        # pas une operation courante — RBAC explicitement restreint a
        # `admin`/`direction` dans ce premier chantier, disclosed comme
        # restriction deliberee, extensible plus tard si un besoin reel
        # apparait pour d'autres roles. Aucun autre role de la matrice ne
        # recoit `automation`.
        "automation": {"view", "add", "change"},
        # `feasibility` (FEA1-3, chantier « etudes de faisabilite », cf.
        # plan) : simuler cout/prix/marge d'un produit hypothetique AVANT
        # tout client/prospect reel est un outil de DECISION, pas une
        # operation courante de tous les roles — restreint explicitement a
        # `admin`/`direction`/`resp_production`/`resp_commercial` (cadrage
        # du chantier), meme discipline que `financing`/`automation`
        # ci-dessus. Aucun autre role de la matrice ne recoit `feasibility`.
        "feasibility": {"view", "add", "change"},
        # `projects` (PJ1-PJ15, cf. plan) : acces complet transverse,
        # meme discipline que le reste de la matrice pour ce role.
        "projects": {"view", "add", "change"},
        # `ai` (AI1, chantier module IA transversal, cf. plan) :
        # l'administration du budget de tokens/cout IA d'un tenant
        # (`AiUsageLimit`/`AiRequest`) est reservee a `admin`/`direction`,
        # meme discipline que `automation`/`financing` ci-dessus — un
        # pilotage de cout, pas une operation courante. Les fonctionnalites
        # IA a usage large (assistant contextuel, recherche, insights,
        # recommandations, AI2-AI7) n'ont volontairement PAS besoin de
        # cette entree : elles seront exposees sans permission de module
        # dediee (meme posture que `chat`, ouvert a tout utilisateur
        # authentifie), disclosed a chaque etape correspondante.
        "ai": {"view", "add", "change"},
        # `helpdesk` (HD1, suivi des demandes/incidents operationnels, cf.
        # plan) : pilotage transverse (gestion SLA/escalade/KB/equipes a
        # venir en HD2-HD4) — acces complet, meme discipline que
        # `automation`/`financing` ci-dessus.
        "helpdesk": {"view", "add", "change"},
        # `pos` (chantier module POS, cahier §13.5) : acces complet, meme
        # discipline transverse que le reste de la matrice pour ce role.
        "pos": {"view", "add", "change"},
        # `simulation` (chantier module Simulation financiere, cahier
        # §13.6) : acces complet, meme discipline transverse que le reste
        # de la matrice pour ce role.
        "simulation": {"view", "add", "change"},
        # `analytics` (chantier fondations Phase 2, cahier §12 — entrepot
        # en etoile + dictionnaire d'indicateurs) : acces complet, meme
        # discipline transverse que le reste de la matrice pour ce role.
        "analytics": {"view", "add", "change"},
        # `bi` (chantier module Business Intelligence, cahier §13.1) :
        # acces complet, meme discipline transverse que le reste de la
        # matrice pour ce role.
        "bi": {"view", "add", "change"},
        # `forecast` (chantier module Forecast, cahier Phase 2 §13.2) :
        # acces complet, meme discipline transverse que le reste de la
        # matrice pour ce role.
        "forecast": {"view", "add", "change"},
        # `whatsapp` (chantier module WhatsApp, cahier Phase 2 §13.4) :
        # module de gouvernance/messagerie CLIENT — pas une operation
        # courante de tous les roles (meme discipline que `financing`/
        # `automation`/`feasibility` ci-dessus) : explicitement restreint a
        # `admin`/`direction`/`commercial`/`resp_commercial` (les deux
        # derniers = "domaine cible" naturel, cf. leurs entrees ci-dessous
        # — la messagerie client relève de leur perimetre CRM/ventes).
        # Aucun autre role de la matrice ne recoit `whatsapp`.
        "whatsapp": {"view", "add", "change"},
    },
    "direction": {
        # Role de pilotage/validation transverse (approbateur frequent des
        # `ApprovalRule` de chaque module) : consultation large + capacite
        # de faire evoluer un enregistrement (valider/annuler/approuver),
        # jamais de creation de donnees operationnelles de premier niveau.
        "accounting": {"view", "change"},
        "crm": {"view", "change"},
        "mrp": {"view", "change"},
        "patronage": {"view", "change"},
        "partners": {"view", "change"},
        "catalog": {"view", "change"},
        "sales": {"view", "change"},
        "purchase": {"view", "change"},
        "stocks": {"view", "change"},
        "logistics": {"view", "change"},
        "presence": {"view", "change"},
        "strategy": {"view", "add", "change"},
        "reporting": {"view", "add", "change"},
        # `financing` : pilotage/validation transverse, meme raisonnement
        # que le reste de ce role — "view"+"change" (jamais "add", pas de
        # creation de dossier de premier niveau par ce role).
        "financing": {"view", "change"},
        "automation": {"view", "add", "change"},
        # `feasibility` : pilotage/validation transverse — acces complet
        # (cf. commentaire du role `admin` ci-dessus pour le cadrage
        # complet du chantier FEA1-3).
        "feasibility": {"view", "add", "change"},
        # `projects` : pilotage/validation transverse, meme raisonnement
        # que le reste de ce role — "view"+"change" (jamais "add").
        "projects": {"view", "change"},
        # `ai` : pilotage/validation transverse du budget de tokens IA,
        # meme raisonnement que le reste de ce role — "view"+"change"
        # (jamais "add", pas de creation de configuration de premier
        # niveau par ce role).
        "ai": {"view", "change"},
        # `helpdesk` (HD1, cf. plan section RBAC) : `admin`/`direction`
        # recoivent tous deux l'acces complet {view, add, change} — pilotage
        # transverse (gestion SLA/escalade/KB/equipes a venir en HD2-HD4),
        # meme discipline que `automation`/`financing` ci-dessus. Les 9
        # autres roles ne recoivent que {view, add} (cf. leurs entrees
        # respectives ci-dessous).
        "helpdesk": {"view", "add", "change"},
        # `pos` : pilotage/validation transverse — "view"+"change" (jamais
        # "add"), meme raisonnement que le reste de ce role.
        "pos": {"view", "change"},
        # `simulation` (chantier module Simulation financiere, cahier
        # §13.6) : EXCEPTION au reste de ce role — acces COMPLET
        # {view, add, change} et non le "view"+"change" transverse
        # habituel de `direction`, meme raisonnement que `strategy`/
        # `reporting`/`automation`/`feasibility` ci-dessus : le cahier
        # nomme litteralement "Dirigeant" comme l'un des DEUX SEULS roles
        # autorises a manipuler l'atelier de scenarios et l'outil IA
        # `paramétrer_simulation` (§13.4, tableau des outils exposes —
        # "Rôles autorisés : Contrôleur de gestion, Dirigeant"), pas
        # seulement a consulter/valider un enregistrement cree par un
        # autre role.
        "simulation": {"view", "add", "change"},
        # `analytics` (chantier fondations Phase 2, cahier §12) : meme
        # raisonnement que `simulation` ci-dessus — le dictionnaire
        # d'indicateurs gouverne et le declenchement du rafraichissement
        # de l'entrepot sont des actes de gouvernance/pilotage, pas une
        # simple consultation.
        "analytics": {"view", "add", "change"},
        # `bi` : meme raisonnement que `simulation`/`analytics` ci-dessus —
        # EXCEPTION au reste de ce role, acces COMPLET (le cahier decrit
        # `direction` comme co-proprietaire du dictionnaire/des rapports
        # gouvernes, pas seulement un consultateur/valideur, §13.1).
        "bi": {"view", "add", "change"},
        # `forecast` (chantier module Forecast, cahier Phase 2 §13.2) :
        # meme discipline/persona que `simulation`/`analytics` ci-dessus —
        # un outil de pilotage technique (rétrotest, ajustement, calendrier),
        # pas un module a large audience comme `bi`.
        "forecast": {"view", "add", "change"},
        # `whatsapp` : pilotage/gouvernance transverse (approbation des
        # modeles, plafond de cout) — acces COMPLET comme `admin` ci-dessus
        # (pas le "view"+"change" habituel de ce role) : la validation des
        # modeles WhatsApp (WA-3) est un acte de gouvernance/pilotage, pas
        # une simple consultation, meme raisonnement que `simulation`/
        # `analytics`/`bi` ci-dessus.
        "whatsapp": {"view", "add", "change"},
    },
    "comptable": {
        "accounting": {"view", "add", "change"},
        "partners": {"view"},
        # `pos` (chantier module POS) : `comptable` n'est PAS "domaine
        # cible" du POS (le caissier l'est, role dedie `caissier`
        # ci-dessous) mais doit pouvoir consulter les sessions/clotures/
        # ecarts pour rapprocher l'ecriture consolidee generee a chaque
        # cloture (`accounting.services.public.create_pos_session_closing_
        # entry_from_source`) — "view" seul, jamais "add"/"change" (le
        # comptable ne cree ni ne modifie une vente ou une session de
        # caisse).
        "pos": {"view"},
        "catalog": {"view"},
        "reporting": {"view", "add"},
        # `bi` (chantier module Business Intelligence, cahier §13.1) :
        # "view" seul, meme baseline transverse que les autres roles non
        # admin/direction/controleur_gestion ci-dessous — consulte les
        # tableaux de bord/rapports auxquels son role donne droit (filtre
        # au niveau indicateur par `AnMetricDefinition.roles_autorises`),
        # ne cree pas de rapport self-service dans ce premier chantier.
        "bi": {"view"},
        # `financing` : role "domaine cible" (assemblage du dossier
        # bancaire, plan de financement, garanties, CREDOC) — acces complet.
        "financing": {"view", "add", "change"},
        # Pas de responsabilite de departement identifiee pour ce role (cf.
        # `apps.strategy.services.scoping.DEPARTMENT_HEAD_ROLES`) : "change"
        # accorde ICI est un droit N2 large (comme pour tous les roles
        # ci-dessous), restreint en pratique par le scoping N3
        # (`scope_objectives_for_user`/`assert_can_manage_level`) a SES
        # PROPRES objectifs individuels — jamais un objectif departement/
        # entreprise, ni ceux d'un tiers.
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : role non "domaine cible" — "view"+"add"
        # uniquement (tout employe peut consulter les tickets et en creer
        # un, cf. plan section RBAC), jamais "change" au niveau app. Le
        # scope N3 (`services.tickets.user_can_manage_ticket`) permet
        # neanmoins a ce role de transitionner/commenter SES PROPRES
        # tickets (requester ou assignee), verifie explicitement dans
        # `apps.helpdesk.api`.
        "helpdesk": {"view", "add"},
    },
    "commercial": {
        "crm": {"view", "add", "change"},
        "partners": {"view", "add", "change"},
        "catalog": {"view"},
        "sales": {"view", "add", "change"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
        # `whatsapp` (chantier module WhatsApp, cahier Phase 2 §13.4) :
        # "domaine cible" pour l'usage OPERATIONNEL (converser, envoyer un
        # message via un modele DEJA approuve, enregistrer/revoquer un
        # consentement — cette derniere action exige "change" au sens
        # Django, cf. `views.py::consent_revoke`). **Limite assumee et
        # disclosee** (meme granularite par app, pas par modele, que le
        # reste de ce registre, cf. docstring de tete ET le meme choix deja
        # fait pour `strategy`/`StgBudget` ci-dessus) : ce "change" donne
        # techniquement aussi acces a l'approbation de modele/au plafond de
        # cout (`WaMessageTemplate`/champs `Tenant`) via l'API, alors que
        # l'ECRAN ne propose ces actions qu'a `can_manage` (calcule sur
        # `whatsapp.change_wamessagetemplate`, meme permission) — a
        # restreindre via une permission personnalisee dediee si ce
        # cloisonnement plus strict s'avere necessaire en pratique.
        "whatsapp": {"view", "add", "change"},
    },
    "resp_commercial": {
        "crm": {"view", "add", "change"},
        "accounting": {"view"},
        "partners": {"view", "add", "change"},
        "catalog": {"view"},
        "sales": {"view", "add", "change"},
        # RG-PAY-9 : "view" seul — `SENSITIVE_FIELDS` masque tous les
        # montants de `PayPayslip`/`PayPayslipLine` a ce role (cf.
        # `apps.core.services.permissions`), cf. commentaire sur le role
        # `rh` plus bas pour la decision de conception complete.
        "payroll": {"view"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        # Responsable de departement identifie (cf. plan `strategy`,
        # `DEPARTMENT_HEAD_ROLES`) : cree/gere les objectifs departement
        # scopes a son propre departement (`apply_scope`/`scope_objectives_
        # for_user`), en plus de ses objectifs individuels.
        "strategy": {"view", "add", "change"},
        # `feasibility` (FEA1-3) : role "domaine cible" cote commercial
        # explicitement retenu par le cadrage du chantier — evalue le
        # potentiel d'une idee de produit avant tout client reel.
        "feasibility": {"view", "add", "change"},
        # `projects` (PJ1) : cf. plan, section RBAC — `resp_commercial`
        # porte la GESTION de projet (creation/edition projets et taches,
        # budget, sprints) faute de role "chef de projet" litteral parmi
        # les 11 roles acquis du CDC. Acces N2 complet ici ; le scoping N3
        # (limiter un `collaborateur` a ses seules taches assignees, cf.
        # role `collaborateur` ci-dessous) ne s'applique PAS a ce role.
        "projects": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
        # `whatsapp` : meme raisonnement/limite disclosee que `commercial`
        # ci-dessus — "domaine cible" operationnel, responsable de
        # departement commercial.
        "whatsapp": {"view", "add", "change"},
    },
    "acheteur": {
        # Domaine cible = `purchase` (PU1, demande d'achat) ; conserve
        # aussi l'acces aux briques mrp deja liees a l'achat (evaluation
        # fournisseur, echantillons, etats de procurement).
        "purchase": {"view", "add", "change"},
        "mrp": {"view", "change"},
        "partners": {"view", "add", "change"},
        "catalog": {"view", "add", "change"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        # Retenu comme responsable de departement "achats" faute d'un role
        # dedie (cf. plan `strategy`, a verifier/affiner si un role
        # "resp_achats" est cree plus tard).
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
    },
    "resp_production": {
        "mrp": {"view", "add", "change"},
        "patronage": {"view", "add", "change"},
        "catalog": {"view"},
        # RG-PAY-9 : idem `resp_commercial` ci-dessus.
        "payroll": {"view"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        "strategy": {"view", "add", "change"},
        # `feasibility` (FEA1-3) : role "domaine cible" cote production
        # (cf. commentaire du role `resp_commercial` ci-dessus pour le
        # cadrage complet).
        "feasibility": {"view", "add", "change"},
        # `projects` (PJ1) : meme raisonnement que `resp_commercial`
        # ci-dessus (co-porteur de la gestion de projet, cf. plan RBAC).
        "projects": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
    },
    "chef_atelier": {
        # Supervision d'atelier : execute/actualise la production, ne cree
        # pas de donnees de configuration (ateliers, nomenclatures...).
        "mrp": {"view", "change"},
        "catalog": {"view"},
        # RG-PAY-9 : idem `resp_commercial` ci-dessus.
        "payroll": {"view"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
    },
    "magasinier": {
        # Domaine cible = `stocks` (construit a partir de ST1, cf. plan) —
        # role de magasinier litteral, acces complet au module. Conserve
        # aussi l'acces (deja accorde avant `stocks`) aux mouvements de
        # composants portes par mrp.
        "stocks": {"view", "add", "change"},
        "mrp": {"view", "change"},
        "catalog": {"view"},
        # Livraisons/expeditions physiques (vehicules, trajets,
        # expeditions) relevent naturellement du meme role, faute d'un
        # role dedie "logisticien" dans les 11 roles acquis du CDC.
        "logistics": {"view", "add", "change"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
    },
    "rh": {
        # Domaine cible = `presence` + `payroll` (ce chantier, RG-PAY-9)
        # — acces complet aux 2.
        "presence": {"view", "add", "change"},
        "payroll": {"view", "add", "change"},
        "reporting": {"view", "add"},
        # `bi` : meme raisonnement que `comptable` ci-dessus.
        "bi": {"view"},
        # Responsable de departement identifie (cf. plan `strategy`) —
        # idem `resp_commercial` ci-dessus.
        "strategy": {"view", "add", "change"},
        # `helpdesk` (HD1) : meme raisonnement que `comptable` ci-dessus.
        "helpdesk": {"view", "add"},
    },
    "collaborateur": {
        # Role par defaut, acces en lecture aux referentiels partages
        # uniquement. `presence` : "view" seulement — le scoping N3 "own"
        # (RG-PRS-9) restreint ensuite cet acces aux SEULES donnees de
        # l'employe lui-meme, applique au niveau de l'endpoint
        # `apps.presence.api` (jamais au niveau de cette matrice N2, qui ne
        # connait pas les enregistrements).
        # `payroll` : AUCUNE entree, delibrement, depuis le cahier des
        # charges Phase 3 (§6.1, decision D1) : "le salarie n'a pas de
        # compte... il n'existe pas de portail salarie" — un collaborateur
        # ne doit avoir aucun acces en self-service a ses propres donnees
        # de paie, le bulletin etant remis par le gestionnaire. Avant cette
        # decision, ce role portait "payroll": {"view"} avec un scoping N3
        # "own" au niveau de `apps.payroll.api`/`apps.payroll.views` — ce
        # scoping devient sans objet, retire avec la permission elle-meme
        # plutot que laisse en code mort.
        "partners": {"view"},
        "catalog": {"view"},
        # "view" seul (pas de generation directe) : un collaborateur
        # consulte le catalogue mais les rapports auxquels il a reellement
        # droit (§RG-PRS-9, "own") restent portes par `RegisteredReport.
        # permission` propre a chaque module, pas par ce role transverse.
        "reporting": {"view"},
        # `bi` : meme raisonnement que `comptable` ci-dessus (§reporting).
        "bi": {"view"},
        "presence": {"view"},
        # "add" : un collaborateur cree ses propres objectifs individuels
        # (RBAC `strategy`, cf. plan) — le scoping N3 (`scope_objectives_
        # for_user`) restreint ensuite la LECTURE/MODIFICATION aux seuls
        # objectifs dont il est createur ou owner.
        "strategy": {"view", "add", "change"},
        # `projects` (PJ1) : cf. plan, section RBAC — un `collaborateur`
        # gere ses taches assignees et son propre suivi du temps, jamais
        # les autres taches/projets. **Limitation N3 explicitement NON
        # cablee a PJ1** (contrairement a "own" `presence`/`payroll`
        # RG-PRS-9/RG-PAY-9, qui existe deja au niveau des endpoints
        # `apps.presence.api`/`apps.payroll.api`) : "view"+"change" ici
        # sont donc, en l'etat, un droit N2 large sur TOUT le module
        # (comme `strategy` avant application de `scope_objectives_
        # for_user` ci-dessus) — aucun endpoint/vue de `projects` a PJ1
        # ne filtre encore par `assignee=request.user`/`owner=request.
        # user`. Ce scoping "own" (candidat naturel : un filtre
        # equivalent a `scope_objectives_for_user`, applique dans
        # `apps.projects.api`/`apps.projects.views`) est explicitement
        # REPORTE a une etape ulterieure (PJ8, suivi du temps, ou une
        # etape RBAC dediee) — PAS un pre-requis de ce squelette PJ1.
        # Pas de "add" : un collaborateur ne cree ni projet ni tache de
        # premier niveau, seulement les met a jour une fois assignees.
        "projects": {"view", "change"},
        # `helpdesk` (HD1, cf. plan section RBAC) : role par defaut — un
        # `collaborateur` peut consulter TOUS les tickets (traçabilite/
        # suivi, pas de retention d'information) et en creer un, mais pas
        # "change" au niveau app. Le scope N3 (`services.tickets.
        # user_can_manage_ticket`) lui permet neanmoins de transitionner/
        # commenter SES PROPRES tickets (requester ou assignee), jamais
        # ceux d'un tiers — verifie explicitement dans `apps.helpdesk.api`.
        "helpdesk": {"view", "add"},
    },
    # `caissier` (12e role, chantier module POS — cahier Phase 1 §13.5,
    # persona "Caissier / vendeur" explicitement nomme §3, cf. le
    # commentaire de `settings.CORE_STANDARD_ROLES` pour le raisonnement
    # complet de cet ajout). Domaine cible = `pos` (acces complet) ;
    # conserve un acces `catalog`/`partners` restreint a "view" (le POS
    # n'a jamais de second catalogue ni de seconde grille de prix, cf.
    # `apps.pos.module.MODULE` — un caissier consulte le catalogue/les
    # clients mais ne les gere pas, ce n'est pas son role).
    "caissier": {
        "pos": {"view", "add", "change"},
        "catalog": {"view"},
        "partners": {"view"},
        # `strategy`/`reporting`/`helpdesk` : meme baseline transverse que
        # les 11 autres roles (cf. `collaborateur` ci-dessus, seul autre
        # role a `reporting: {"view"}` seul plutot que `{"view","add"}`
        # — un caissier consulte les rapports auxquels il a droit, ne
        # genere pas de rapport ad hoc) — un caissier reste un employe qui
        # gere ses propres objectifs et peut signaler/suivre un ticket,
        # independamment de son domaine cible `pos`.
        "strategy": {"view", "add", "change"},
        "reporting": {"view"},
        # `bi` : meme raisonnement que `comptable` ci-dessus (§reporting).
        "bi": {"view"},
        "helpdesk": {"view", "add"},
    },
    # `controleur_gestion` (13e role, chantier module Simulation financiere
    # — cahier Phase 1 §13.6, persona "Contrôleur de gestion" explicitement
    # nomme §3 : "manipuler des hypothèses sur les vraies données et voir
    # l'effet immédiatement... aujourd'hui dans un tableur déconnecté des
    # données", cf. le commentaire de `settings.CORE_STANDARD_ROLES` pour
    # le raisonnement complet de cet ajout). Domaine cible = `simulation`
    # (acces complet) ; `reporting`/`accounting`/`sales` en lecture seule
    # (le controleur de gestion manipule des hypotheses SUR les donnees
    # reelles, il ne cree ni ne modifie ni devis/facture ni ecriture —
    # seul le moteur de simulation, jamais un document metier, cf. SIM-5).
    "controleur_gestion": {
        "simulation": {"view", "add", "change"},
        # `analytics` (chantier fondations Phase 2, cahier §12) : le
        # controleur de gestion est le proprietaire naturel du dictionnaire
        # d'indicateurs gouverne et du pilotage de l'entrepot decisionnel
        # (meme persona que `simulation` ci-dessus, cf. cahier Phase 2 §3).
        "analytics": {"view", "add", "change"},
        # `bi` (chantier module Business Intelligence, cahier §13.1) : acces
        # complet — le controleur de gestion cree/publie les rapports
        # self-service et les tableaux de bord, memes discipline et
        # justification que `analytics`/`simulation` ci-dessus.
        "bi": {"view", "add", "change"},
        # `forecast` (chantier module Forecast, cahier Phase 2 §13.2) : le
        # controleur de gestion est le proprietaire naturel de l'atelier de
        # prevision (rétrotest, ajustement, publication) — meme persona que
        # `simulation`/`analytics`/`bi` ci-dessus.
        "forecast": {"view", "add", "change"},
        "reporting": {"view", "add"},
        "accounting": {"view"},
        "sales": {"view"},
        "catalog": {"view"},
        "partners": {"view"},
        # `strategy`/`helpdesk` : meme baseline transverse que les 12
        # autres roles (cf. `caissier` ci-dessus).
        "strategy": {"view", "add", "change"},
        "helpdesk": {"view", "add"},
    },
}

# RG-PAY-9 (§5.10.6, stricte) : "managers ne voient AUCUN montant" — parmi
# les 11 roles CDC, aucun n'est nomme "manager" ; `resp_production`/
# `chef_atelier`/`resp_commercial` sont les 3 roles qui encadrent
# effectivement une equipe (via `presence.PrsEmployee.manager`). Chacun
# recoit "view" sur `payroll` ci-dessus (acces a l'EXISTENCE/l'etat d'un
# bulletin, ex. pour verifier qu'un membre d'equipe est bien paye) — SANS
# que cela leur donne acces aux MONTANTS : `SENSITIVE_FIELDS` (cf.
# `apps.core.services.permissions`) masque explicitement tout champ
# monetaire de `PayPayslip`/`PayPayslipLine` a ces 3 roles (seuls `rh`/
# `direction`/`admin` les voient) — decision de conception documentee ici
# plutot qu'un "managers = aucun acces du tout", qui aurait ete un
# sur-refus non demande par le CDC (celui-ci dit "aucun montant" QUE sur
# les montants, pas sur l'existence/l'etat du bulletin).

# Permissions personnalisees (non auto-generees, declarees explicitement
# dans un `Meta.permissions` de modele — ex. `AccMove.Meta.permissions`) a
# accorder en plus du view/add/change generique ci-dessus. Ajout minimal
# pour ce lot (T6, wiring accounting/crm) : comptable/direction/admin
# recoivent les deux permissions de transition FSM sur les factures
# (`accounting.validate_accmove`, `accounting.cancel_accmove`) — la
# premiere est desormais utilisee par `apps.accounting.api.validate_invoice_
# endpoint`, la seconde par l'ecran HTMX `apps.accounting.views.invoice_
# detail` (action "cancel"). PU5 (RG-PUR-3) ajoute `purchase.run_reordering`
# (`PurReorderingRule.Meta.permissions`) pour `POST /purchase/reordering/
# run` — admin/direction (pilotage transverse) et acheteur (domaine cible
# de `purchase`, cf. `ROLE_APP_PERMISSIONS["acheteur"]`) la recoivent.
# {role_code: {"app_label.codename", ...}}
#
# Chantier RG-QUALIF : `qualify_accimportrow`/`qualify_accinvoiceimportrow`/
# `qualify_stkimportrow` (declares en `Meta.permissions` des modeles de
# ligne d'import concernes) gardent le nouvel endpoint `POST .../rows/
# {id}/qualify` — accordes aux roles "domaine cible" de chaque module
# (comptable pour accounting, magasinier pour stocks, cf.
# `ROLE_APP_PERMISSIONS`) ainsi qu'a admin/direction (pilotage transverse,
# meme discipline que le reste de ce registre). L'ACTE D'APPROUVER, lui,
# passe par l'endpoint generique deja existant `POST /approvals/{id}/
# decide` (gate par role via `ApprovalRule.approver_role`, jamais un
# nouveau codename ici).
# PJ5 (facturation multi-modes de `projects`) : `projects.bill_prjproject`
# (declaree en `Meta.permissions` de `PrjProject`) garde les 4 endpoints de
# declenchement de facturation (`POST /projects/{id}/bill/...`) — une
# operation plus sensible que le simple CRUD projet/tache deja couvert par
# `ROLE_APP_PERMISSIONS["projects"]` ci-dessus (genere une ecriture
# comptable engageant le tenant vis-a-vis d'un client). Restreinte a
# `admin`/`direction` (pilotage transverse, meme discipline que le reste de
# ce registre) et `resp_commercial` (co-porteur historique de la gestion de
# projet, cf. `ROLE_APP_PERMISSIONS["resp_commercial"]["projects"]` —
# seul des 2 co-porteurs a recevoir ce droit : `resp_production` gere la
# production/les taches mais n'est pas le role qui negocie/engage la
# facturation client).
CUSTOM_PERMISSIONS_BILL_PRJPROJECT_ROLES = ("admin", "direction", "resp_commercial")

# PJ7 (heatmap de capacite + champs personnalises `projects`) :
# `projects.manage_prjcustomfielddefinition` (declaree en `Meta.permissions`
# de `PrjCustomFieldDefinition`) contourne la granularite app-level de
# `ROLE_APP_PERMISSIONS["projects"]` (qui accorderait sinon add/view/change
# sur CE modele a `resp_commercial`/`resp_production` aussi, cf. sa
# docstring de module) — meme mecanisme deja etabli par
# `CUSTOM_PERMISSIONS_BILL_PRJPROJECT_ROLES` ci-dessus. Configurer les
# champs personnalises est un PARAMETRAGE (comme `accounting/views_config.
# py`), pas une operation courante de gestion de projet — restreint a
# `admin`/`direction` uniquement, ni `resp_commercial` ni `resp_production`
# (contrairement a `bill_prjproject`, qui associe ce dernier).
CUSTOM_PERMISSIONS_MANAGE_PRJ_CUSTOM_FIELD_ROLES = ("admin", "direction")

# PJ8 (suivi du temps `projects`) : `projects.track_prjtimeentry`
# (declaree en `Meta.permissions` de `PrjTimeEntry`) contourne, dans le
# sens INVERSE des 2 permissions personnalisees ci-dessus, la granularite
# app-level de `ROLE_APP_PERMISSIONS["projects"]` — celle-ci n'accorde PAS
# "add" au role `collaborateur` (cf. sa docstring de role : CRUD projet/
# tache reserve aux roles "domaine cible"), or un `collaborateur` DOIT
# pouvoir demarrer/arreter SON PROPRE chrono (cf. plan PJ8, disclosure
# explicite depuis PJ1 : "un collaborateur gere ses taches assignees et son
# propre suivi du temps"). Accordee a TOUS les roles ayant acces au module
# `projects` (admin/direction/resp_commercial/resp_production/
# collaborateur) — le scope N3 ("un utilisateur ne gere que SES PROPRES
# entrees") est porte par `apps.projects.services.time_tracking`
# lui-meme, jamais par cette permission N2.
CUSTOM_PERMISSIONS_TRACK_PRJ_TIME_ENTRY_ROLES = (
    "admin",
    "direction",
    "resp_commercial",
    "resp_production",
    "collaborateur",
)

# HD2 (chantier `helpdesk`, cf. plan section RBAC) : `helpdesk.
# manage_hlpslapolicy`/`manage_hlpescalationrule`/`run_helpdesk_checks`
# (declarees en `Meta.permissions` de `HlpSlaPolicy`/`HlpEscalationRule`)
# contournent, dans le MEME sens que `manage_prjcustomfielddefinition`
# ci-dessus, la granularite app-level de `ROLE_APP_PERMISSIONS["helpdesk"]`
# (qui accorderait sinon add/view sur CES modeles a TOUS les 9 roles non
# admin/direction, cf. sa docstring de module) — le plan exige que la
# configuration SLA/escalade et le declenchement manuel des verifications
# restent `admin`/`direction` UNIQUEMENT, un PARAMETRAGE/pilotage
# transverse, pas une operation courante de suivi de ticket.
CUSTOM_PERMISSIONS_MANAGE_HLP_ROLES = ("admin", "direction")

# RSK1-2 (chantier risques operationnels) : `RiskItem` vit dans `core`
# (rattachable a n'importe quel module via content_type/object_id, cf.
# `apps.core.models.risk`) — `core` n'apparait PAS dans
# `ROLE_APP_PERMISSIONS` ci-dessus (aucun role n'a jamais recu d'acces
# generique a TOUS les modeles `core`, ex. `Tenant`/`User`/`Document`), donc
# accorder les permissions par app aurait ouvert bien plus que le seul
# registre de risques. Choix : codenames auto-generes Django
# (`core.add_riskitem`/`core.view_riskitem`/`core.change_riskitem`) ajoutes
# ICI, meme mecanisme que les permissions personnalisees ci-dessus (bien
# qu'auto-generees, `_custom_permissions_for_role` les resout de la meme
# facon par `codename`+`app_label`). Simplification assumee (disclosed,
# demandee explicitement par le cadrage du chantier) : `admin`/`direction`
# recoivent les 3 actions (voient/gerent TOUS les risques, aucun scoping
# N3) ; `acheteur`/`resp_production`/`resp_commercial`/`rh` (roles
# "domaine cible" plausibles pour signaler un risque sur leur perimetre)
# ne recoivent QUE `add`/`view` — pas `change` — le visionnage de LEURS
# PROPRES risques est filtre au niveau service (`owner=request.user`, cf.
# `apps.core.views.risk`/`apps.core.api_risk`), pas un scope N3 complexe
# par entite rattachee. Consequence assumee : ces 4 roles ne peuvent pas
# eux-memes cloturer/modifier un risque qu'ils ont signale via l'API
# generique gate par permission — seuls `admin`/`direction` le peuvent
# aujourd'hui (a affiner si un besoin reel de "l'auteur peut cloturer son
# propre signalement" est exprime plus tard).
_RISK_FULL_ROLES = ("admin", "direction")
_RISK_ADD_VIEW_ROLES = ("acheteur", "resp_production", "resp_commercial", "rh")

# QLT1-2 (chantier qualite : preparation, controle, suivi, certifications) :
# meme raisonnement que RSK1-2 ci-dessus — `QltChecklistTemplate`/
# `QltInspection` vivent dans `core` (rattachables a n'importe quel module
# via content_type/object_id, cf. `apps.core.models.quality`), `core`
# n'apparait pas dans `ROLE_APP_PERMISSIONS`, donc les codenames
# auto-generes Django sont ajoutes ICI. Roles "domaine cible" retenus par le
# cadrage du lot : `resp_production`/`chef_atelier` (pilotage qualite en
# atelier/production) et `acheteur` (controle qualite a reception
# fournisseur, cf. `apps.purchase`) recoivent les 3 actions sur les 2
# modeles — contrairement a RSK1-2, pas de scoping "owner" ici (une
# inspection qualite est une donnee d'equipe, pas un signalement personnel
# a filtrer par auteur) donc aucune raison de limiter ces roles a
# `add`/`view` seulement. `admin`/`direction` recoivent les 3 actions
# (pilotage transverse, meme discipline que partout ailleurs dans ce
# registre). Aucun autre role ne recoit d'acces (pas de lecture seule
# generalisee : aucune exigence explicite du cadrage ne la demande, et
# l'ouvrir a tous les roles aurait ete plus large que ce que RSK1-2 a fait
# pour un besoin similaire).
_QLT_FULL_ROLES = ("admin", "direction", "resp_production", "chef_atelier", "acheteur")

# PRC1-3 (chantier veille prix fournisseurs Chine/Europe) :
# `PrcPriceWatchTarget`/`PrcPriceSnapshot` vivent dans `purchase` (jamais
# dans `core` — contrairement a RSK1-2/QLT1-2 ci-dessus, ces entites ne
# sont pas rattachables a n'importe quel module) : les codenames
# auto-generes `purchase.view_prcpricewatchtarget`/`add_*`/`change_*` (et
# idem pour `prcpricesnapshot`) sont donc DEJA couverts par la matrice
# app-large `ROLE_APP_PERMISSIONS["purchase"] = {"view", "add", "change"}`
# (admin/direction/acheteur) definie plus haut — aucun ajout necessaire
# ici pour le CRUD. Seule la permission personnalisee
# `purchase.run_price_watch_check` (declaree en `Meta.permissions` de
# `PrcPriceWatchTarget`, meme patron que `purchase.run_reordering` pour
# RG-PUR-3) est ajoutee ci-dessous pour l'endpoint de declenchement manuel
# — memes roles que `run_reordering` : admin/direction (pilotage
# transverse) et acheteur (domaine cible de `purchase`).
CUSTOM_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "purchase.run_reordering",
        "purchase.run_price_watch_check",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
        "stocks.qualify_stkimportrow",
        "whatsapp.run_message_retry",
    },
    "direction": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "purchase.run_reordering",
        "purchase.run_price_watch_check",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
        "stocks.qualify_stkimportrow",
        "whatsapp.run_message_retry",
    },
    "comptable": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
    },
    "acheteur": {"purchase.run_reordering", "purchase.run_price_watch_check"},
    "magasinier": {"stocks.qualify_stkimportrow"},
    # WA-7 (cahier Phase 2 §13.4) : « reprise dediee au canal WhatsApp » —
    # memes roles que le reste de la gouvernance `whatsapp`
    # (`ROLE_APP_PERMISSIONS`, commentaire dedie sur le role `admin`) :
    # admin/direction (pilotage transverse) + commercial/resp_commercial
    # (domaine cible operationnel, relance un envoi client en echec).
    "commercial": {"whatsapp.run_message_retry"},
    "resp_commercial": {"whatsapp.run_message_retry"},
}

for _role in _RISK_FULL_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).update(
        {"core.add_riskitem", "core.view_riskitem", "core.change_riskitem"}
    )
for _role in _RISK_ADD_VIEW_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).update({"core.add_riskitem", "core.view_riskitem"})

for _role in CUSTOM_PERMISSIONS_BILL_PRJPROJECT_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).add("projects.bill_prjproject")
for _role in CUSTOM_PERMISSIONS_MANAGE_PRJ_CUSTOM_FIELD_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).add("projects.manage_prjcustomfielddefinition")
for _role in CUSTOM_PERMISSIONS_TRACK_PRJ_TIME_ENTRY_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).add("projects.track_prjtimeentry")
for _role in CUSTOM_PERMISSIONS_MANAGE_HLP_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).update(
        {
            "helpdesk.manage_hlpslapolicy",
            "helpdesk.manage_hlpescalationrule",
            "helpdesk.run_helpdesk_checks",
        }
    )
for _role in _QLT_FULL_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).update(
        {
            "core.add_qltchecklisttemplate",
            "core.view_qltchecklisttemplate",
            "core.change_qltchecklisttemplate",
            "core.add_qltinspection",
            "core.view_qltinspection",
            "core.change_qltinspection",
        }
    )

# UXR1 (gestion des utilisateurs) : `core.manage_users` (declaree en
# `Meta.permissions` de `core.User`) garde les 2 nouveaux ecrans admin
# (`apps.core.views.admin_users.admin_user_list`/`admin_user_edit`) — meme
# patron que `projects.bill_prjproject` ci-dessus. `core` n'apparait pas
# dans `ROLE_APP_PERMISSIONS` (aucun role n'a jamais recu d'acces generique
# a TOUT modele `core`, cf. RSK1-2/QLT1-2), donc cette permission
# personnalisee est la SEULE porte d'entree de cet ecran. Restreinte a
# `admin`/`direction` uniquement (pilotage transverse des comptes,
# operation sensible — jamais un role "domaine cible").
CUSTOM_PERMISSIONS_MANAGE_USERS_ROLES = ("admin", "direction")
for _role in CUSTOM_PERMISSIONS_MANAGE_USERS_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).add("core.manage_users")

# PT2 (chantier "fiche partenaire a onglets par role") :
# `accounting.manage_partneraccountassignment` (declaree en `Meta.
# permissions` de `AccPartnerRoleAccount`) contourne la granularite
# app-level de `ROLE_APP_PERMISSIONS` — celle-ci accorde deja `partners:
# {view,add,change}` a commercial/resp_commercial/acheteur (edition
# courante de la fiche partenaire) mais seulement `accounting: {view}` a
# ces memes roles, et inversement `comptable` a `accounting: {view,add,
# change}` mais `partners: {view}` seul. Assigner/modifier le compte
# comptable d'un partenaire par role est un geste du domaine COMPTABLE
# pose sur une fiche `partners` — reserve explicitement a comptable/admin/
# direction (decision actee avec l'utilisateur), jamais aux roles
# "domaine commercial" qui gerent deja le reste de la fiche partenaire.
CUSTOM_PERMISSIONS_MANAGE_PARTNER_ACCOUNT_ROLES = ("admin", "direction", "comptable")
for _role in CUSTOM_PERMISSIONS_MANAGE_PARTNER_ACCOUNT_ROLES:
    CUSTOM_PERMISSIONS.setdefault(_role, set()).add("accounting.manage_partneraccountassignment")

# Chantier sauvegarde/restauration/reinitialisation : PAS de permission
# personnalisee ici (contrairement au premier jet de ce chantier, corrige
# apres coup par le commanditaire) — sauvegarde/restauration/
# reinitialisation/planification sont reservees au SEUL
# superadministrateur (`request.user.is_superuser`), jamais a un role
# `admin`/`direction` via ce mecanisme RBAC generique (qui n'attribue des
# droits qu'a des GROUPES : une permission classique ici aurait
# automatiquement laisse passer `admin`/`direction`, ce qui n'est pas
# voulu). Le garde reel vit directement dans les vues/endpoints
# (`apps.core.api_backup`/`apps.core.views.backup_admin`), verifie
# `is_superuser` sans intermediaire RBAC — cf. `apps.core.models.backup.
# TenantDataOperation` pour le meme rappel.

_DJANGO_ACTIONS = ("view", "add", "change")


def _custom_permissions_for_role(role_code: str) -> list[Permission]:
    """Resout les permissions personnalisees (non auto-generees) de
    `CUSTOM_PERMISSIONS` pour un role donne, en objets `Permission`."""
    permissions: list[Permission] = []
    for full_codename in CUSTOM_PERMISSIONS.get(role_code, set()):
        app_label, codename = full_codename.split(".", 1)
        permissions.append(
            Permission.objects.get(codename=codename, content_type__app_label=app_label)
        )
    return permissions


def _permissions_for_app(app_label: str, actions: set[str]) -> list[Permission]:
    prefixes = tuple(f"{action}_" for action in actions if action in _DJANGO_ACTIONS)
    if not prefixes:
        return []
    content_types = ContentType.objects.filter(app_label=app_label)
    return [
        perm
        for perm in Permission.objects.filter(content_type__in=content_types)
        if perm.codename.startswith(prefixes)
    ]


def sync_group_permissions(group: Group, role_code: str) -> int:
    """Aligne les permissions Django d'un `Group` sur `ROLE_APP_PERMISSIONS`
    pour le role donne — idempotent (remplace integralement l'ensemble des
    permissions du groupe pour rester coherent si la matrice change).
    Retourne le nombre de permissions assignees."""
    app_permissions = ROLE_APP_PERMISSIONS.get(role_code, {})
    permissions: list[Permission] = []
    for app_label, actions in app_permissions.items():
        permissions.extend(_permissions_for_app(app_label, actions))
    permissions.extend(_custom_permissions_for_role(role_code))
    group.permissions.set(permissions)
    return len(permissions)
