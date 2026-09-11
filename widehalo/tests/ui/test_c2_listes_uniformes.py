"""C-2 — toutes les listes des quatre modules offrent la meme chose.

**L'exigence.** « Toutes les listes sont uniformes, avec pagination,
boutons d'exportation Excel et PDF, filtre et recherche. » Avant ce lot,
neuf listes de `crm`, `sales`, `accounting` et `logistics` passaient par
`smart_table_response` et en beneficiaient ; seize autres etaient des
`<table>` ecrites a la main, sans pagination, sans export, sans
recherche. Une liste de comptes ou de journaux comptables se lisait donc
d'un bloc, quelle que soit sa longueur, et ne s'exportait pas.

**Ce que cette garde verifie, et pourquoi ces marqueurs.** Elle ne
regarde pas le code des vues mais ce qui ARRIVE AU NAVIGATEUR : une vue
peut appeler le bon helper et un gabarit oublier d'inclure le composant —
c'est precisement le genre d'ecart qu'une lecture du code ne voit pas.
Les trois marqueurs sont ceux que `components/_smart_table.html` rend
inconditionnellement : le champ de recherche (`name="q"`), le bloc des
trois exports, et la navigation de pagination.

**L'export est verifie en le DEMANDANT**, pas en constatant la presence
d'un lien : un lien d'export qui rendrait la page HTML au lieu d'un
fichier satisferait une assertion de presence et ne servirait a rien.

**La liste des ecrans est declaree, et son exhaustivite est gardee**
(`test_the_declared_list_still_covers_every_list_screen`) : un jeu ferme
qui ne se verifie que contre lui-meme s'endort — lecon F60 de T6.
"""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import grant_module_access
from django.test import Client

pytestmark = pytest.mark.django_db

#: Les ecrans de LISTE des quatre modules. Ne figurent PAS ici, et c'est
#: delibere : les hubs a tuiles (`config_index`, `reports`), les
#: formulaires de creation, le kanban (lot C-4), les ecrans de reglage
#: (`config_fiscal`), les ecrans d'import et la declaration de TVA — aucun
#: n'est une liste d'enregistrements qu'on pagine, filtre ou exporte.
#:
#: `config_fiscal_years` en est exclu, et le motif est technique autant
#: que fonctionnel : cet ecran ANNOTE chaque exercice avec ce qui empeche
#: de le clore (`closing_blockers`, critere T2/ACC-10 — « montrer le
#: blocage AVANT que l'utilisateur ne clique »). L'annotation se fait en
#: Python sur une liste materialisee ; `smart_table_response` pagine un
#: queryset et rendrait la colonne vide. Migrer cet ecran couterait le
#: critere qu'il sert, pour gagner une pagination sur une liste qui compte
#: quelques exercices.
#:
#: `config_default_accounts` en est exclu avec son motif : c'est une
#: MATRICE role -> compte, pas une liste. Chaque ligne y est un role connu
#: du produit, jamais un enregistrement saisi ; la paginer n'aurait pas de
#: sens et l'exporter encore moins.
ECRANS_DE_LISTE = (
    "/crm/",
    "/crm/config/lost-reasons/",
    "/crm/config/pipelines/",
    "/crm/config/teams/",
    "/sales/",
    "/sales/orders/",
    "/sales/config/recurrences/",
    "/accounting/",
    "/accounting/payments/notifications/",
    "/accounting/quick-entry/",
    "/accounting/config/accounts/",
    "/accounting/config/journals/",
    "/accounting/config/payment-terms/",
    "/accounting/config/periods/",
    "/accounting/config/taxes/",
    "/logistics/",
    "/logistics/drivers/",
    "/logistics/trips/",
    "/logistics/shipments/",
    "/logistics/trip-templates/",
    "/logistics/config/hs-codes/",
    "/logistics/config/packaging-types/",
    "/logistics/config/service-providers/",
)


def _client_dote() -> tuple[Client, Tenant, User]:
    """Un utilisateur qui detient les quatre modules.

    `grant_module_access` et non `grant_role` : les trois roles qui
    detiennent `accounting` en ecriture sont soumis au MFA obligatoire, et
    `force_login` renverrait alors vers `/mfa/`."""
    tenant = Tenant.objects.create(code="C2-LISTES", name="Societe C-2")
    user = User.objects.create_user(email="c2@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "accounting", "crm", "sales", "logistics")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user


#: Ecrans qui rendent un ETAT VIDE PEDAGOGIQUE plutot qu'un tableau vide
#: quand ils n'ont aucune ligne — c'est le critere CRM-5, et c'est un
#: meilleur ecran, pas un manquement : un tableau vide ne dit pas si
#: l'utilisateur n'a rien, s'il a mal filtre, ou si le module n'est pas
#: configure. Le test seme donc une ligne avant de verifier les controles,
#: au lieu de constater leur absence et de conclure a tort.
A_AMORCER = {"/crm/"}


def _amorcer(chemin: str, tenant: Tenant, user: User) -> None:
    """`salesperson=user` n'est pas un detail : `scope_leads_for_user`
    (RG-CRM-5, niveau N3) ne montre a un utilisateur SANS role de pilotage
    que les opportunites dont il est le commercial. `grant_module_access`
    accorde les permissions N2 sans donner de NOM de role — cet
    utilisateur est donc traite comme un commercial ordinaire, et une
    opportunite sans commercial lui resterait invisible. La liste
    afficherait alors son etat vide, et le test conclurait a tort a
    l'absence des controles."""
    if chemin == "/crm/":
        from apps.core.tenant_context import activate_tenant
        from apps.crm.services.leads import create_lead_quick

        with activate_tenant(tenant.id):
            create_lead_quick(tenant=tenant, name="Opportunite temoin C-2", salesperson=user)


@pytest.mark.parametrize("chemin", ECRANS_DE_LISTE)
def test_every_list_offers_search_export_and_pagination(chemin: str) -> None:
    """La moitie visible de l'exigence, ecran par ecran."""
    client, tenant, user = _client_dote()
    if chemin in A_AMORCER:
        _amorcer(chemin, tenant, user)
    # `presentation=liste` est DEMANDE explicitement depuis C-4 : cinq de
    # ces ecrans s'ouvrent desormais en kanban par defaut, et la pagination
    # est propre a la liste — un tableau ne se pagine pas, il plafonne par
    # colonne et l'annonce. Ce test porte sur l'uniformite de la LISTE ;
    # l'accord des deux presentations est verifie par
    # `tests/ui/test_c4_kanban.py`.
    reponse = client.get(chemin, {"presentation": "liste"})
    assert reponse.status_code == 200, f"{chemin} rend {reponse.status_code}"
    contenu = reponse.content.decode()

    manquants = [
        nom
        for nom, marqueur in (
            ("recherche", "smart-table-search-"),
            ("export", "smart-table-export-links"),
            ("pagination", 'class="pagination"'),
        )
        if marqueur not in contenu
    ]
    assert not manquants, (
        f"{chemin} n'offre pas : {', '.join(manquants)}. Cette liste ne passe pas par "
        f"`smart_table_response` / `components/_smart_table.html`, ou son gabarit a "
        f"oublie d'inclure le composant."
    )


@pytest.mark.parametrize("chemin", ECRANS_DE_LISTE)
def test_every_list_actually_exports(chemin: str) -> None:
    """L'export se verifie en le DEMANDANT.

    Un lien d'export qui rendrait la page HTML satisferait le test
    precedent et ne servirait a rien le jour ou quelqu'un clique.

    **Sans parametre de presentation, volontairement** : exporter porte sur
    les DONNEES, pas sur la facon de les disposer. Un ecran qui s'ouvre en
    kanban doit exporter aussi bien qu'en liste, sinon l'utilisateur devrait
    basculer pour obtenir son fichier — et C-4 a failli introduire
    exactement ce defaut."""
    client, _tenant, _user = _client_dote()
    reponse = client.get(chemin, {"export": "csv"})
    assert reponse.status_code == 200, f"{chemin}?export=csv rend {reponse.status_code}"
    assert "text/csv" in reponse["Content-Type"], (
        f"{chemin}?export=csv rend {reponse['Content-Type']} au lieu d'un CSV."
    )
    assert "attachment" in reponse.get("Content-Disposition", ""), (
        f"{chemin}?export=csv ne se telecharge pas."
    )


def test_the_declared_list_still_covers_every_smart_table_screen() -> None:
    """Un jeu ferme qui ne se verifie que contre lui-meme s'endort.

    `ECRANS_DE_LISTE` est ecrit a la main : rien n'empeche d'y oublier une
    liste ajoutee demain, et les deux tests ci-dessus passeraient alors en
    l'ignorant. Cette garde recalcule la verite depuis le RESOLVEUR d'URL —
    une source independante de la liste qu'elle surveille (lecon F60 de
    T6) — et exige que toute vue des quatre modules servie par
    `smart_table_response` y figure.

    Elle ne verifie PAS l'inverse : `ECRANS_DE_LISTE` peut legitimement
    contenir un chemin dont la vue n'utilise pas encore le composant, le
    temps de la migration — c'est meme ainsi que ce lot a commence, avec
    quinze echecs."""
    import inspect

    from django.urls import get_resolver
    from django.urls.resolvers import URLPattern, URLResolver

    modules = ("crm", "sales", "accounting", "logistics")
    servies: set[str] = set()

    def marcher(noeud, chemin: str) -> None:
        for entree in noeud.url_patterns:
            if isinstance(entree, URLResolver):
                marcher(entree, chemin + str(entree.pattern))
            elif isinstance(entree, URLPattern) and entree.name:
                vue = entree.callback
                while hasattr(vue, "__wrapped__"):
                    vue = vue.__wrapped__
                try:
                    fichier = inspect.getsourcefile(vue) or ""
                    source = inspect.getsource(vue)
                except (OSError, TypeError):
                    return
                if any(f"/apps/{m}/views" in fichier for m in modules) and (
                    "smart_table_response" in source
                ):
                    servies.add("/" + chemin + str(entree.pattern))

    marcher(get_resolver(), "")
    assert servies, "Aucune vue trouvee : c'est l'instrument qui est casse, pas le depot."

    oubliees = sorted(servies - set(ECRANS_DE_LISTE))
    assert not oubliees, (
        f"Ces ecrans passent par `smart_table_response` mais ne figurent pas dans "
        f"ECRANS_DE_LISTE : {oubliees}. Ajoutez-les — sans quoi une regression sur "
        f"leur pagination, leur export ou leur recherche ne serait vue par personne."
    )
