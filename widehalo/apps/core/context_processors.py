from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from apps.core.models.tenant import Tenant
from apps.core.models.user import DENSITY_CHOICES, THEME_CHOICES
from apps.core.services.permissions import user_role_codes
from apps.core.services.rbac_policy import CUSTOM_PERMISSIONS, ROLE_APP_PERMISSIONS

_ADMIN_ROLE_CODES = {"admin", "direction"}

# Les 18 app labels reels des liens « Modules metier » de la sidebar (cf.
# `templates/base.html`), tels qu'ils apparaissent verbatim dans les cles de
# `ROLE_APP_PERMISSIONS`. `RiskItem` (19e lien, "Registre des risques") vit
# dans l'app `core` (cf. `rbac_policy.py`, section RSK1-2) — `core`
# n'apparait jamais comme cle de `ROLE_APP_PERMISSIONS` (aucun role n'a
# d'acces generique a TOUS les modeles `core`), donc ce lien est
# special-case ci-dessous via `_RISK_MENU_KEY`/`_RISK_PERMISSION_CODENAME`
# plutot que traite comme un app label ordinaire.
# "pos" ajoute par le chantier module POS (cahier §13.5, audit
# docs/audit/2026-09-cahier-des-charges-v3-audit.md) : lien sidebar
# "Point de vente" (`templates/base.html`), groupe accordeon "commercial"
# ci-dessous (memes utilisateurs que crm/sales, cf. `ROLE_APP_PERMISSIONS
# ["caissier"]`).
# "simulation" ajoute par le chantier module Simulation financiere (cahier
# §13.6) : lien sidebar "Simulation financière" (`templates/base.html`),
# groupe accordeon "finance-pilotage" ci-dessous (memes utilisateurs que
# accounting/financing — direction/comptable/controleur_gestion, cf.
# `ROLE_APP_PERMISSIONS["controleur_gestion"]`).
_MODULE_APP_LABELS: tuple[str, ...] = (
    "accounting",
    "crm",
    "logistics",
    "mrp",
    "patronage",
    "presence",
    "purchase",
    "sales",
    "pos",
    "stocks",
    "payroll",
    "reporting",
    "feasibility",
    "projects",
    "helpdesk",
    "strategy",
    "financing",
    "automation",
    "simulation",
)
_RISK_MENU_KEY = "risks"
_RISK_PERMISSION_CODENAME = "core.view_riskitem"

# Les 7 groupes accordeon de la sidebar (cle utilisee par `menuGroup(key)`,
# cf. static/js/ui_patterns.js), chacun associe aux app labels/cles
# `visible_app_labels` de ses liens.
_MENU_GROUPS: dict[str, tuple[str, ...]] = {
    "pour-tous": ("reporting", "strategy", "helpdesk"),
    "commercial": ("crm", "sales", "pos", "feasibility"),
    "achats-logistique": ("purchase", "stocks", "logistics"),
    "production": ("mrp", "patronage"),
    "finance-pilotage": ("accounting", "financing", "automation", "simulation"),
    "rh": ("presence", "payroll"),
    "projets-risques": ("projects", _RISK_MENU_KEY),
}


def tenant(request: HttpRequest) -> dict[str, Tenant | None]:
    """Expose `current_tenant` a tous les templates (footer/header — chantier
    UI signale par l'utilisateur : le nom de la societe doit rester visible
    sur toute page).

    `Tenant.objects` (TenantManager) filtre deja sur le tenant courant via
    la contextvar deja positionnee par `TenantMiddleware` a ce stade du
    cycle de requete (le rendu de template a lieu a l'interieur de la vue,
    donc apres `TenantMiddleware.__call__`) — pas de nouvelle resolution de
    session necessaire ici. Retourne toujours `None` proprement (jamais
    d'exception) pour un visiteur anonyme ou avant creation de la premiere
    societe."""
    return {"current_tenant": Tenant.objects.first()}


def visible_app_labels_for(user: Any) -> frozenset[str]:
    """Calcule les cles (app labels ordinaires + `_RISK_MENU_KEY`) des 18
    liens « Modules metier » auxquels `user` a acces — `is_superuser` voit
    tout ; sinon, au moins un des roles de l'utilisateur doit porter
    `"view"` dans `ROLE_APP_PERMISSIONS[role].get(app_label, set())` (le
    lien risques est special-case via `CUSTOM_PERMISSIONS`, cf. commentaire
    de module ci-dessus). Retourne toujours un frozenset propre (jamais
    d'exception), y compris vide pour un visiteur anonyme."""
    if not user.is_authenticated:
        return frozenset()
    if user.is_superuser:
        return frozenset((*_MODULE_APP_LABELS, _RISK_MENU_KEY))

    roles = user_role_codes(user)
    visible = {
        app_label
        for app_label in _MODULE_APP_LABELS
        if any("view" in ROLE_APP_PERMISSIONS.get(role, {}).get(app_label, set()) for role in roles)
    }
    if any(_RISK_PERMISSION_CODENAME in CUSTOM_PERMISSIONS.get(role, set()) for role in roles):
        visible.add(_RISK_MENU_KEY)
    return frozenset(visible)


def account(request: HttpRequest) -> dict[str, Any]:
    """Expose `is_admin_user` (chantier menu compte utilisateur / section
    Administration) et, depuis UXR2, `visible_app_labels`/`visible_groups`
    a tous les templates — permet a `base.html` de conditionner
    l'affichage de la section Administration ainsi que des 18 liens/7
    groupes accordeon « Modules metier » (filtrage RBAC N1) sans dupliquer
    ce calcul dans chaque vue.

    Meme idiome que le reste du depot pour verifier un role depuis du HTML
    classique (`user_role_codes(user) & {...}`, deja utilise par
    `apps/payroll/views.py`/`apps/sales/views.py`/`apps/ai/views.py`) —
    jamais `require_permission()` (django-ninja uniquement). Retourne
    toujours des valeurs vides proprement (jamais d'exception) pour un
    visiteur anonyme ou sans tenant."""
    user = request.user
    visible_app_labels = visible_app_labels_for(user)
    visible_groups = {
        key: any(label in visible_app_labels for label in labels)
        for key, labels in _MENU_GROUPS.items()
    }
    # `visible_group_keys` (frozenset des SEULES cles vraies) : les cles de
    # groupe contiennent des tirets ("achats-logistique", ...) que la
    # notation pointee des templates Django ne sait pas parser
    # (`{% if dict.cle-avec-tiret %}` leve `TemplateSyntaxError`) — `base.
    # html` teste donc `"cle" in visible_group_keys` plutot que `visible_
    # groups.cle`. `visible_groups` (dict[str, bool]) reste expose tel que
    # specifie (utilisable directement par les tests).
    visible_group_keys = frozenset(key for key, is_visible in visible_groups.items() if is_visible)

    # Bascule de shell (Sprint 1 / L0 de la refonte UX, cf.
    # docs/planning/2026-refonte-ux-sprints.md) : strangler pattern au
    # niveau du shell applicatif — un utilisateur qui active la nouvelle
    # interface (session, cf. `apps.core.views.pages.toggle_shell`) la
    # garde sur toute la navigation jusqu'a desactivation explicite.
    # Legacy par defaut (`False`) : aucun utilisateur n'est bascule
    # automatiquement.
    use_new_shell = bool(request.session.get("use_new_shell", False))

    # Sprint 10 (L6 Personnalisation & offline) : `resolved_theme` est la
    # valeur reellement posee sur `<html data-theme="...">` par
    # `base.html`/`tw-launchpad.html`. `User.theme == "system"` (defaut) se
    # resout ici en "light" cote serveur -- la resolution reelle du
    # `prefers-color-scheme` du systeme reste une amelioration cote client
    # (petit script inline, ne s'applique qu'avec JS actif), pour que la
    # page reste correcte/utilisable sans JS, juste sans matcher la
    # preference OS. `density_class` alimente `<body class="...">`.
    user_theme = getattr(user, "theme", "system") if user.is_authenticated else "system"
    # "widehalo"/"widehalo-dark" : noms des 2 themes DaisyUI (cf.
    # static/css/tailwind-input.css) attendus tels quels par
    # `<html data-theme="...">` -- distincts des valeurs stockees sur
    # `User.theme` ("light"/"dark"/"system"), qui restent le vocabulaire
    # utilisateur (formulaire de preferences).
    resolved_theme = "widehalo-dark" if user_theme == "dark" else "widehalo"
    density_class = (
        f"density-{getattr(user, 'density', 'comfortable')}"
        if user.is_authenticated
        else "density-comfortable"
    )
    # Un visiteur anonyme n'a pas de preference stockee -- traite comme
    # "system" (comportement par defaut du script prefers-color-scheme).
    theme_is_system = user_theme == "system"

    if not user.is_authenticated:
        return {
            "is_admin_user": False,
            "visible_app_labels": visible_app_labels,
            "visible_groups": visible_groups,
            "visible_group_keys": visible_group_keys,
            "use_new_shell": use_new_shell,
            "resolved_theme": resolved_theme,
            "density_class": density_class,
            "theme_choices": THEME_CHOICES,
            "density_choices": DENSITY_CHOICES,
            "theme_is_system": theme_is_system,
        }
    is_admin = bool(user_role_codes(user) & _ADMIN_ROLE_CODES) or user.is_superuser
    return {
        "is_admin_user": is_admin,
        "visible_app_labels": visible_app_labels,
        "visible_groups": visible_groups,
        "visible_group_keys": visible_group_keys,
        "use_new_shell": use_new_shell,
        "resolved_theme": resolved_theme,
        "density_class": density_class,
        "theme_choices": THEME_CHOICES,
        "density_choices": DENSITY_CHOICES,
        "theme_is_system": theme_is_system,
    }
