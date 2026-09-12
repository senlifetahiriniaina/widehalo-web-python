"""Helpers de test reutilisables pour activer un tenant (contexte applicatif
+ session Postgres), en dehors du cycle de requete HTTP normalement gere par
TenantMiddleware. Alias de `apps.core.tenant_context.activate_tenant` — les
tests l'utilisent sous le nom historique `use_tenant`."""

from collections.abc import Sequence

from django.contrib.auth.models import Group

from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant as use_tenant

__all__ = ["grant_module_access", "grant_permissions", "grant_role", "use_tenant"]


def grant_role(user: User, role_code: str) -> Group:
    """Attribue a `user` le role `role_code` (ex. "comptable") avec les
    permissions Django reellement synchronisees selon
    `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS` — a utiliser dans
    tout test qui appelle un endpoint API protege par `require_permission()`,
    plutot que de recreer un Group/Permission ad hoc par test."""
    group, _ = Group.objects.get_or_create(name=role_code)
    sync_group_permissions(group, role_code)
    user.groups.add(group)
    return group


def grant_module_access(
    user: User, *app_labels: str, actions: tuple[str, ...] = ("view", "add", "change")
) -> Group:
    """Accorde les permissions Django d'un ou plusieurs modules SANS role.

    **Pourquoi ce helper existe, et pourquoi `grant_role` ne suffit pas.**
    Le module `accounting` n'est detenu en ecriture que par `admin`,
    `direction` et `comptable` — les trois soumis au MFA obligatoire
    (`settings.CORE_MFA_REQUIRED_ROLES`). Un test d'ECRAN qui ferait
    `grant_role(user, "comptable")` puis `force_login` verrait le
    middleware le renvoyer vers `/mfa/` : son assertion porterait sur une
    redirection sans aucun rapport avec ce qu'il croit tester. Le piege a
    deja coute deux passes a cette vague.

    Ce helper donne les DROITS sans le NOM DE ROLE qui declenche le MFA :
    le groupe cree porte un nom neutre, donc `user_role_codes` n'y voit
    aucun role connu. Un test d'ecran eprouve ainsi l'ecran, et le MFA
    reste eprouve par les tests de MFA.

    A n'utiliser que dans des tests d'ecran. Pour verifier la POLITIQUE
    elle-meme — quel role peut quoi — c'est `grant_role` qu'il faut, sans
    quoi le test prouverait le mecanisme au lieu de la regle."""
    from django.contrib.auth.models import Permission

    nom = "test-access-" + "-".join(sorted(app_labels)) + "-" + "-".join(sorted(actions))
    group, _ = Group.objects.get_or_create(name=nom)
    prefixes = tuple(f"{action}_" for action in actions)
    permissions = [
        permission
        for permission in Permission.objects.filter(content_type__app_label__in=app_labels)
        if permission.codename.startswith(prefixes)
    ]
    group.permissions.add(*permissions)
    user.groups.add(group)
    return group


def grant_permissions(
    user: User, *, app_label: str, codenames: Sequence[str], nom: str | None = None
) -> Group:
    """Accorde des permissions NOMMEES UNE A UNE, sans elargir au module.

    **Pourquoi ce helper existe a cote de `grant_module_access`.** Huit
    fichiers de test portaient chacun leur propre `_grant()` — quatre
    signatures differentes pour le meme geste. Les fondre dans
    `grant_module_access` aurait paru plus simple et aurait ete FAUX : ce
    helper-la raisonne par ACTION (`view_`/`add_`/`change_` sur tous les
    modeles d'une app), la ou ces tests accordent des codenames PRECIS
    parce que leur propriete depend de ce qui MANQUE.

    L'exemple qui tranche :
    `reporting.test_generate_endpoint_denies_when_missing_underlying_report_permission`
    donne `add_rptjob` et `view_rptjob`, et exige un 403 faute de
    `accounting.view_accaccount`. Elargir ses droits reviendrait a effacer
    ce que le test eprouve — le defaut exact paye sur
    `test_partner_edit_forbidden_without_change_permission`, ou un
    `grant_module_access` a rendu vrai ce qui devait rester faux.

    Le groupe porte un nom NEUTRE et derive : aucun role connu, donc pas de
    MFA (cf. `grant_module_access` et docs/RBAC.md §1.3).
    """
    from django.contrib.auth.models import Permission

    codenames = tuple(codenames)
    # `nom` reste accepte pour les appelants qui nommaient deja leur groupe :
    # deux groupes distincts portant les memes droits ne sont pas equivalents
    # partout (un test peut compter les groupes d'un utilisateur).
    nom = nom or ("test-perms-" + app_label + "-" + "-".join(sorted(codenames)))
    group, _ = Group.objects.get_or_create(name=nom[:150])
    group.permissions.add(
        *Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
    )
    user.groups.add(group)
    return group
