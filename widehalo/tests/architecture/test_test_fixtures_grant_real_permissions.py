"""Garde H-1 : un groupe de test qui porte le NOM d'un role sans porter ses
PERMISSIONS est une fixture qui ment.

**Ce qu'elle empeche.** C-1 l'a mesure a ses depens : en posant 82 gardes
d'ecran sur `crm`, `sales`, `accounting` et `logistics`, **90 tests sont
tombes d'un coup — aucun ne testant le RBAC**. Tous construisaient leur
utilisateur par `Group.objects.get_or_create(name="comptable")` : un groupe
portant le NOM du role et AUCUNE permission Django. Ils passaient uniquement
parce qu'aucun ecran ne verifiait de droit. La meme avalanche attend chaque
module que C-5 gardera.

**Ce qu'elle N'empeche PAS, et c'est le coeur du sujet.** Six mecanismes du
produit se resolvent sur le NOM du role, jamais sur une permission. Pour
eux, le groupe nu est JUSTE, et `grant_role` serait au mieux inutile, au
pire faux :

1. le MFA obligatoire (`settings.CORE_MFA_REQUIRED_ROLES`, lu par
   `user_role_codes`) ;
2. le menu lateral et la coquille (`visible_app_labels_for` lit la matrice
   EN MEMOIRE, pas la base — divergence documentee dans `docs/RBAC.md`) ;
3. la portee par enregistrement N3 (`crm.scope_leads_for_user`,
   `pos.services.scoping`, `simulation.services.scoping`) ;
4. le moteur d'approbation (`ApprovalRule.approver_role` et
   `fallback_approver_role`) ;
5. le routage de notification (`notify_role`) ;
6. les vues et services gardes par CODE DE ROLE plutot que par permission
   (`core/views/pages.py`, `payroll/views.py`, `sales` pour la marge,
   `bi.services.query`).

D'ou la forme de cette garde : elle ne refuse pas le patron, elle refuse
qu'il soit employe **sans motif ecrit**. C'est le patron de
`_ONE_SHOT_COMMANDS` et d'`ABSENCES_MOTIVEES`.

**L'instrument dit ce qui l'a convaincu** — regle inscrite apres sept
erreurs de mesure dans ce projet, et cet instrument-ci s'est trompe SIX
fois avant de tenir :

- il a cherche `sync_group_permissions` et rate `permissions.add` — donc
  declare morts 26 fichiers qui attachent de vraies `Permission` a la main ;
- il a ignore les helpers LOCAUX `_grant()` (huit signatures differentes) ;
- il a compte les seeders de production comme de la dette ;
- il a classe `crm/test_scoping.py` en « groupe decoratif » alors que la
  portee N3 se lit precisement sur le nom du role.

Il classe donc sur DEUX axes independants, et c'est leur croisement — jamais
un compte — qui nomme le remede.

**Le jeu ferme se verifie contre une liste independante** (lecon F60) : les
codes de role sont relus depuis `ROLE_APP_PERMISSIONS`, jamais depuis la
liste de motifs que cette garde surveille.

**Ce que cette garde NE PEUT PAS voir, et il faut le lire avant de s'y
fier.** Elle raisonne par FICHIER : des qu'un fichier emploie l'un des
`MOYENS`, elle le considere instruit et ne regarde plus ses groupes. Un
groupe nu isole dans un fichier par ailleurs correct lui echappe donc. Et,
plus grave, elle ne suit pas les IMPORTS : `payroll/tests/factories.py`
fabrique `staff_client()` avec son role et son device TOTP, si bien que
quatre fichiers de `payroll` sont en regle sans qu'aucune ligne ne le
montre chez eux. Une mesure statique par fichier a sur-declare SEPT fois
dans ce projet ; la seule mesure fiable de « qui tombera quand C-5
gardera » se prend a l'EXECUTION, en observant les permissions reelles de
l'utilisateur a chaque requete. Cette garde empeche la dette de revenir ;
elle ne la mesure pas.
"""

from __future__ import annotations

import pathlib
import re

from apps.core.services.rbac_policy import ROLE_APP_PERMISSIONS

#: Racine du projet Django (le repertoire qui contient `apps/` et `tests/`).
RACINE = pathlib.Path(__file__).resolve().parents[2]

#: Les seeders sont du code de PRODUCTION : ils creent legitimement les
#: groupes de roles, et `load_roles` leur synchronise leurs permissions.
#: `apps/core/tests/utils.py` EST le helper correct : il ne peut pas etre
#: sa propre dette.
EXCLUS = ("/management/commands/", "apps/core/tests/utils.py")

#: Les moyens reconnus d'attacher de vraies permissions a un groupe. Un
#: fichier qui emploie l'un d'eux n'est pas en dette, quelle que soit la
#: facon dont il nomme ses groupes.
MOYENS = (
    "permissions.add",
    "sync_group_permissions",
    "grant_role(",
    "grant_module_access(",
    # H-1b : huit fichiers ont cede leur `_grant()` local a ce helper. Sans
    # cette entree, ils perdaient leur `permissions.add` et leurs groupes
    # correctement nommes repassaient pour de la dette — la garde l'a vu.
    "grant_permissions(",
)

#: La dette MOTIVEE, au 12/09/2026 : chaque entree est un fichier ou le nom
#: du role EST le mecanisme teste, avec le nombre exact de sites et la
#: raison. Trois gardes la tiennent : aucun site neuf hors de cette liste,
#: aucune entree qui enfle, aucune entree perimee (anti-cimetiere).
#:
#: Cette liste peut RETRECIR. Elle ne peut jamais s'allonger sans qu'on
#: ecrive lequel des six mecanismes ci-dessus est en jeu.
MOTIFS: dict[str, tuple[int, str]] = {
    # 1 — MFA : le middleware lit le NOM du role, pas une permission.
    "apps/core/tests/test_mfa_enforcement.py": (1, "MFA : declenche par CORE_MFA_REQUIRED_ROLES"),
    "apps/core/tests/test_mfa_web.py": (1, "MFA : declenche par CORE_MFA_REQUIRED_ROLES"),
    "apps/payroll/tests/factories.py": (1, "MFA : le harnais enrole lui-meme le device TOTP"),
    # 2 — Menu et coquille : la matrice est lue EN MEMOIRE, pas en base.
    "apps/core/tests/test_account_menu.py": (2, "menu : visible_app_labels_for lit la matrice"),
    "tests/ui/test_menu_rbac.py": (4, "menu : la politique testee EST le nom du role"),
    "tests/ui/test_shell_toggle.py": (1, "coquille : visibilite de module par role"),
    # 3 — Portee par enregistrement (N3).
    "apps/crm/tests/test_scoping.py": (3, "portee N3 : scope_leads_for_user lit le code de role"),
    "apps/pos/tests/test_sessions.py": (1, "portee N3 : pos.services.scoping, admin transverse"),
    # 4 — Moteur d'approbation : l'approbateur se designe par son role.
    "apps/crm/tests/test_pipeline_and_discounts.py": (
        3,
        "approbation : ApprovalRule.approver_role",
    ),
    "apps/purchase/tests/test_orders.py": (3, "approbation : ApprovalRule.approver_role"),
    "apps/purchase/tests/test_acceptance.py": (1, "approbation : approve_substitute lit le role"),
    "apps/purchase/tests/test_requisitions.py": (1, "approbation : approve_substitute lit le role"),
    "apps/purchase/tests/test_substitution.py": (1, "approbation : approve_substitute lit le role"),
    "apps/purchase/tests/test_reordering.py": (1, "approbation : le demandeur est un acheteur"),
    "apps/purchase/tests/test_price_watch.py": (2, "approbation : la veille notifie les acheteurs"),
    # 5 — Routage de notification : notify_role resout par code de role.
    "apps/ai/tests/test_automated_insights.py": (1, "notify_role : destinataire par role"),
    "apps/automation/tests/test_seed_flows.py": (1, "notify_role : destinataire par role"),
    "apps/catalog/tests/test_int1_events.py": (1, "notify_role : destinataire par role"),
    "apps/core/tests/test_notifications_grouping.py": (2, "notify_role : regroupement par role"),
    "apps/crm/tests/test_int1_events.py": (1, "notify_role : destinataire par role"),
    "apps/feasibility/tests/test_int1_events.py": (2, "notify_role : destinataire par role"),
    "apps/partners/tests/test_int1_events.py": (1, "notify_role : destinataire par role"),
    "apps/patronage/tests/test_int1_events.py": (1, "notify_role : destinataire par role"),
    "apps/quality/tests/test_alerts.py": (1, "notify_role : destinataire par role"),
    "apps/quality/tests/test_run_quality_control_checks_command.py": (
        1,
        "notify_role : destinataire par role",
    ),
    "apps/stocks/tests/test_expiry_alerts.py": (1, "notify_role : destinataire par role"),
    "apps/stocks/tests/test_run_expiry_alerts_command.py": (
        1,
        "notify_role : destinataire par role",
    ),
    # 6 — Vues et services gardes par CODE DE ROLE, jamais par permission.
    "apps/core/tests/test_company_profile.py": (
        2,
        "garde par code de role : pages.py verifie _ADMIN_ROLE_CODES, pas une permission",
    ),
    "apps/sales/tests/test_ai_data_query_registration.py": (
        2,
        "masquage de marge : margin_report filtre sur user_role_codes",
    ),
}

_APPEL = re.compile(r"Group\.objects\.get_or_create\(\s*name=(?:f?[\"']([^\"']*)[\"']|([\w.]+))")


def _fichiers_de_test() -> list[pathlib.Path]:
    trouves: list[pathlib.Path] = []
    for base in ("apps", "tests"):
        for chemin in (RACINE / base).rglob("*.py"):
            relatif = chemin.relative_to(RACINE).as_posix()
            if any(exclu in relatif for exclu in EXCLUS):
                continue
            if "/tests/" in relatif or chemin.name.startswith("test_"):
                trouves.append(chemin)
    return trouves


def _codes_de_role() -> frozenset[str]:
    """Les codes de role, relus a la SOURCE et jamais depuis `MOTIFS`."""
    return frozenset(ROLE_APP_PERMISSIONS)


def _sites_nus(chemin: pathlib.Path) -> list[tuple[int, str]]:
    """(ligne, nom) des groupes portant un code de role SANS permission.

    Un nom construit (`name=role_code`, `name=f"{role}"`) compte : c'est
    une fixture parametree par le role, donc un site de la meme famille.
    """
    texte = chemin.read_text(encoding="utf-8")
    if "Group.objects.get_or_create" not in texte:
        return []
    if any(moyen in texte for moyen in MOYENS):
        return []
    roles = _codes_de_role()
    sites: list[tuple[int, str]] = []
    for numero, ligne in enumerate(texte.splitlines(), start=1):
        trouve = _APPEL.search(ligne)
        if trouve is None:
            continue
        litteral, variable = trouve.group(1), trouve.group(2)
        if litteral is not None:
            if litteral in roles:
                sites.append((numero, litteral))
        elif variable is not None and "role" in variable.lower():
            sites.append((numero, f"<{variable}>"))
    return sites


def _releve() -> dict[str, list[tuple[int, str]]]:
    releve: dict[str, list[tuple[int, str]]] = {}
    for chemin in _fichiers_de_test():
        sites = _sites_nus(chemin)
        if sites:
            releve[chemin.relative_to(RACINE).as_posix()] = sites
    return releve


def test_aucune_fixture_nue_hors_des_motifs_ecrits() -> None:
    """Un groupe au nom d'un role, sans permission et sans motif, est refuse."""
    releve = _releve()
    inconnus = {fichier: sites for fichier, sites in releve.items() if fichier not in MOTIFS}
    assert not inconnus, (
        "Fixture(s) portant le NOM d'un role sans ses PERMISSIONS, et sans motif ecrit :\n"
        + "\n".join(
            f"  - {fichier}:{ligne} (name={nom})"
            for fichier, sites in sorted(inconnus.items())
            for ligne, nom in sites
        )
        + "\n\nDeux remedes, jamais un troisieme :\n"
        "  * le test frappe une surface gardee par une PERMISSION -> "
        '`grant_module_access(user, "<app>")` pour un test d\'ECRAN '
        '(nom de groupe neutre, donc pas de MFA), `grant_role(user, "<role>")` '
        "pour un test qui eprouve la POLITIQUE elle-meme ;\n"
        "  * le test eprouve l'un des six mecanismes qui se lisent sur le NOM "
        "du role (MFA, menu, portee N3, approbation, notify_role, garde par "
        "code de role) -> inscrivez-le dans `MOTIFS` avec sa raison."
    )


def test_aucune_entree_de_motif_nenfle() -> None:
    """Un fichier deja motive ne gagne pas de site neuf en silence."""
    releve = _releve()
    enfles = {
        fichier: (len(releve.get(fichier, [])), attendu)
        for fichier, (attendu, _raison) in MOTIFS.items()
        if len(releve.get(fichier, [])) > attendu
    }
    assert not enfles, (
        "Fichier(s) motive(s) portant PLUS de fixtures nues que declare :\n"
        + "\n".join(
            f"  - {fichier} : {mesure} trouvees, {attendu} declarees"
            for fichier, (mesure, attendu) in sorted(enfles.items())
        )
        + "\n\nUn motif couvre un nombre PRECIS de sites. Si le site neuf releve "
        "du meme mecanisme, montez le compte ; sinon, il est en dette."
    )


def test_aucune_entree_de_motif_nest_perimee() -> None:
    """Anti-cimetiere : une entree qui ne decrit plus rien doit disparaitre."""
    releve = _releve()
    perimees = {
        fichier: (len(releve.get(fichier, [])), attendu)
        for fichier, (attendu, _raison) in MOTIFS.items()
        if len(releve.get(fichier, [])) < attendu
    }
    assert not perimees, (
        "Entree(s) de `MOTIFS` perimee(s) — la dette a retreci, la liste doit suivre :\n"
        + "\n".join(
            f"  - {fichier} : {mesure} trouvees, {attendu} declarees"
            for fichier, (mesure, attendu) in sorted(perimees.items())
        )
    )


def test_chaque_motif_nomme_un_mecanisme() -> None:
    """Un motif vide ne motive rien."""
    muets = [fichier for fichier, (_n, raison) in MOTIFS.items() if len(raison.strip()) < 15]
    assert not muets, f"Motif(s) trop court(s) pour dire quoi que ce soit : {muets}"


def test_la_mesure_voit_encore_des_fixtures() -> None:
    """Auto-test : un instrument qui ne trouve plus rien s'est casse.

    Le plancher porte sur le CORPUS, pas sur la dette : c'est le nombre de
    fichiers de test qui creent un groupe, quelle que soit leur categorie.
    Il ne bouge pas quand la dette est payee — c'est precisement ce qu'on
    lui demande.
    """
    createurs = [
        chemin
        for chemin in _fichiers_de_test()
        if "Group.objects.get_or_create" in chemin.read_text(encoding="utf-8")
    ]
    # Plancher abaisse de 60 a 55 par H-1b, et la raison est verifiee : huit
    # fichiers ont cede leur `_grant()` local au helper de `core`, donc ils
    # n'appellent plus `Group.objects.get_or_create` eux-memes. Le corpus
    # mesure est passe de 60 a 58 pour cette raison-la, pas parce que
    # l'instrument aurait cesse de chercher au bon endroit.
    assert len(createurs) >= 55, (
        f"L'instrument ne voit plus que {len(createurs)} fichiers creant un groupe. "
        "Avant de baisser ce plancher, verifiez qu'il n'a pas cesse de chercher "
        "au bon endroit — c'est arrive six fois dans ce projet."
    )


def test_les_codes_de_role_viennent_de_la_matrice_et_non_de_cette_garde() -> None:
    """Le jeu ferme se verifie contre une source independante (lecon F60)."""
    roles = _codes_de_role()
    assert len(roles) >= 10, f"Matrice de roles anormalement petite : {sorted(roles)}"
    for atendu in ("admin", "comptable", "magasinier", "acheteur"):
        assert atendu in roles, f"`{atendu}` a disparu de ROLE_APP_PERMISSIONS"
