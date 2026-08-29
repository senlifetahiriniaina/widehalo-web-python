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
        "strategy": {"view", "add", "change"},
        # §5.11 reporting : catalogue/generation pour tous les roles
        # (le filtrage reel par rapport passe par `RegisteredReport.
        # permission`, deja porte par le module cible — ex. un rapport
        # `accounting` reste invisible a qui n'a pas `accounting.view_*`) ;
        # "change" (gestion des planifications RPT-7) reserve a
        # admin/direction, pilotage transverse comme le reste de la matrice.
        "reporting": {"view", "add", "change"},
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
    },
    "comptable": {
        "accounting": {"view", "add", "change"},
        "partners": {"view"},
        "catalog": {"view"},
        "reporting": {"view", "add"},
        # Pas de responsabilite de departement identifiee pour ce role (cf.
        # `apps.strategy.services.scoping.DEPARTMENT_HEAD_ROLES`) : "change"
        # accorde ICI est un droit N2 large (comme pour tous les roles
        # ci-dessous), restreint en pratique par le scoping N3
        # (`scope_objectives_for_user`/`assert_can_manage_level`) a SES
        # PROPRES objectifs individuels — jamais un objectif departement/
        # entreprise, ni ceux d'un tiers.
        "strategy": {"view", "add", "change"},
    },
    "commercial": {
        "crm": {"view", "add", "change"},
        "partners": {"view", "add", "change"},
        "catalog": {"view"},
        "sales": {"view", "add", "change"},
        "reporting": {"view", "add"},
        "strategy": {"view", "add", "change"},
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
        # Responsable de departement identifie (cf. plan `strategy`,
        # `DEPARTMENT_HEAD_ROLES`) : cree/gere les objectifs departement
        # scopes a son propre departement (`apply_scope`/`scope_objectives_
        # for_user`), en plus de ses objectifs individuels.
        "strategy": {"view", "add", "change"},
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
        # Retenu comme responsable de departement "achats" faute d'un role
        # dedie (cf. plan `strategy`, a verifier/affiner si un role
        # "resp_achats" est cree plus tard).
        "strategy": {"view", "add", "change"},
    },
    "resp_production": {
        "mrp": {"view", "add", "change"},
        "patronage": {"view", "add", "change"},
        "catalog": {"view"},
        # RG-PAY-9 : idem `resp_commercial` ci-dessus.
        "payroll": {"view"},
        "reporting": {"view", "add"},
        "strategy": {"view", "add", "change"},
    },
    "chef_atelier": {
        # Supervision d'atelier : execute/actualise la production, ne cree
        # pas de donnees de configuration (ateliers, nomenclatures...).
        "mrp": {"view", "change"},
        "catalog": {"view"},
        # RG-PAY-9 : idem `resp_commercial` ci-dessus.
        "payroll": {"view"},
        "reporting": {"view", "add"},
        "strategy": {"view", "add", "change"},
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
        "strategy": {"view", "add", "change"},
    },
    "rh": {
        # Domaine cible = `presence` + `payroll` (ce chantier, RG-PAY-9)
        # — acces complet aux 2.
        "presence": {"view", "add", "change"},
        "payroll": {"view", "add", "change"},
        "reporting": {"view", "add"},
        # Responsable de departement identifie (cf. plan `strategy`) —
        # idem `resp_commercial` ci-dessus.
        "strategy": {"view", "add", "change"},
    },
    "collaborateur": {
        # Role par defaut, acces en lecture aux referentiels partages
        # uniquement. `presence`/`payroll` : "view" seulement — le
        # scoping N3 "own" (RG-PRS-9/RG-PAY-9) restreint ensuite cet acces
        # aux SEULES donnees de l'employe lui-meme, applique au niveau des
        # endpoints `apps.presence.api`/`apps.payroll.api` (jamais au
        # niveau de cette matrice N2, qui ne connait pas les
        # enregistrements).
        "partners": {"view"},
        "catalog": {"view"},
        # "view" seul (pas de generation directe) : un collaborateur
        # consulte le catalogue mais les rapports auxquels il a reellement
        # droit (§RG-PAY-9, "own") restent portes par `RegisteredReport.
        # permission` propre a chaque module, pas par ce role transverse.
        "reporting": {"view"},
        "presence": {"view"},
        "payroll": {"view"},
        # "add" : un collaborateur cree ses propres objectifs individuels
        # (RBAC `strategy`, cf. plan) — le scoping N3 (`scope_objectives_
        # for_user`) restreint ensuite la LECTURE/MODIFICATION aux seuls
        # objectifs dont il est createur ou owner.
        "strategy": {"view", "add", "change"},
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
CUSTOM_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "purchase.run_reordering",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
        "stocks.qualify_stkimportrow",
    },
    "direction": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "purchase.run_reordering",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
        "stocks.qualify_stkimportrow",
    },
    "comptable": {
        "accounting.validate_accmove",
        "accounting.cancel_accmove",
        "accounting.qualify_accimportrow",
        "accounting.qualify_accinvoiceimportrow",
    },
    "acheteur": {"purchase.run_reordering"},
    "magasinier": {"stocks.qualify_stkimportrow"},
}

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
