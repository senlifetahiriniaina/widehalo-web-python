"""C-1 — les ecrans refusent enfin ce que l'API refusait deja.

**Ce que ces tests defendent.** Avant ce lot, les 82 vues de `crm`,
`sales`, `accounting` et `logistics` portaient `@login_required` et RIEN
d'autre : n'importe quel utilisateur authentifie, quel que soit son role,
lisait ET ecrivait le plan comptable, le referentiel fiscal, les tournees
et les devis. L'API des memes modules appliquait pourtant deja le RBAC N2
(`@require_permission("accounting.view_accaccount")` & consorts) : l'ecran
et l'endpoint refusaient donc des personnes differentes pour la meme
operation.

**Les roles temoins sont choisis dans la matrice, pas inventes** — un
temoin mal choisi prouverait le mecanisme au lieu de la politique :

- `caissier` n'a AUCUN des quatre modules : il eprouve le refus total ;
- `magasinier` a `logistics` en view/add/change et rien d'autre : il
  eprouve que la garde est PAR MODULE et non un refus en bloc ;
- `controleur_gestion` a `view` sur `sales` et `accounting` et rien de
  plus : il eprouve la lecture seule — GET 200, POST 403 — par un vrai
  role de la matrice plutot que par une permission accordee a la main.

Aucun des trois n'est dans `CORE_MFA_REQUIRED_ROLES`, donc `force_login`
suffit. `admin`, `direction` et `comptable` y sont : pour eux il faudrait
enroler un device TOTP, piege deja paye deux fois dans cette vague.

**Les deux fuites que ces tests ferment et qu'un test « de page » ne
verrait pas** : l'export `?export=csv` d'une liste, qui rend TOUT le
queryset en piece jointe, et les telechargements de rapports, qui ne
rendent aucun gabarit et n'auraient donc ete couverts par aucune
verification d'ecran.
"""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role
from django.test import Client

pytestmark = pytest.mark.django_db


def _client_pour(role: str, email: str) -> tuple[Client, Tenant]:
    """Un utilisateur authentifie portant `role`, rattache a une societe."""
    tenant = Tenant.objects.create(code=f"C1-{role[:8].upper()}", name="Societe C-1")
    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    grant_role(user, role)
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    assert not mfa_service.mfa_required_for_user(user), (
        f"Le role {role} est soumis au MFA : `force_login` ne suffit pas et le "
        f"middleware renverrait vers /mfa/, donc l'assertion porterait sur une "
        f"redirection sans rapport avec le droit teste."
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


#: Une page de LECTURE par module, et le codename qui la garde.
ECRANS_DE_LECTURE = (
    ("/crm/", "crm"),
    ("/sales/", "sales"),
    ("/accounting/", "accounting"),
    ("/logistics/", "logistics"),
)

#: Une page d'ECRITURE par module (POST).
ECRANS_D_ECRITURE = (
    ("/crm/new/", "crm"),
    ("/sales/new/", "sales"),
    ("/accounting/new/", "accounting"),
    ("/logistics/vehicles/new/", "logistics"),
)


def test_a_role_without_the_module_is_refused_everywhere() -> None:
    """`caissier` n'a aucun des quatre modules — ni en lecture ni en ecriture."""
    client, _ = _client_pour("caissier", "c1-caissier@example.com")
    for chemin, module in ECRANS_DE_LECTURE:
        assert client.get(chemin).status_code == 403, f"lecture de {module} non refusee"
    for chemin, module in ECRANS_D_ECRITURE:
        assert client.get(chemin).status_code == 403, f"ecran d'ecriture {module} non refuse"
        assert client.post(chemin, {}).status_code == 403, f"ecriture {module} non refusee"


def test_the_guard_is_per_module_and_not_a_blanket_refusal() -> None:
    """`magasinier` detient `logistics` et rien d'autre.

    Sans ce test, une garde qui refuserait TOUT LE MONDE PARTOUT passerait
    le test precedent — c'est exactement la panne que le crawler d'ecrans
    ne savait pas voir avant C-1a."""
    client, _ = _client_pour("magasinier", "c1-magasinier@example.com")
    assert client.get("/logistics/").status_code == 200
    assert client.get("/logistics/vehicles/new/").status_code == 200
    for chemin in ("/crm/", "/sales/", "/accounting/"):
        assert client.get(chemin).status_code == 403, f"{chemin} devrait etre refuse"


def test_a_read_only_role_reads_but_cannot_write() -> None:
    """`controleur_gestion` a `view` sur `sales` et `accounting`, sans plus.

    C'est la propriete que la matrice declare et que l'ecran ignorait :
    lire n'est pas ecrire."""
    client, _ = _client_pour("controleur_gestion", "c1-controleur@example.com")
    assert client.get("/sales/").status_code == 200
    assert client.get("/accounting/").status_code == 200
    # L'ecran de creation se LIT (view) mais son POST est refuse (add).
    assert client.post("/sales/new/", {}).status_code == 403
    assert client.post("/accounting/new/", {}).status_code == 403
    assert client.get("/crm/").status_code == 403


def test_the_csv_export_of_a_list_is_refused_too() -> None:
    """`smart_table_response` rend TOUT le queryset en piece jointe sur
    `?export=csv`.

    Une garde posee dans le gabarit plutot qu'au sommet de la vue aurait
    laisse cette porte grande ouverte : l'export ne rend pas le gabarit."""
    client, _ = _client_pour("caissier", "c1-export@example.com")
    for chemin in ("/crm/", "/sales/", "/accounting/", "/logistics/"):
        reponse = client.get(chemin, {"export": "csv"})
        assert reponse.status_code == 403, f"l'export CSV de {chemin} n'est pas refuse"


def test_report_downloads_are_refused() -> None:
    """Les telechargements de rapports ne rendent AUCUN gabarit : ils
    n'auraient ete couverts par aucune verification d'ecran, et rendent
    pourtant des donnees completes."""
    client, _ = _client_pour("caissier", "c1-rapports@example.com")
    for chemin in (
        "/crm/reports/activities/",
        "/sales/reports/revenue/",
        "/sales/reports/margin/",
        "/logistics/reports/shipments/",
    ):
        assert client.get(chemin).status_code == 403, f"{chemin} n'est pas refuse"


def test_the_refusal_page_says_what_is_missing_and_to_whom_to_turn() -> None:
    """Un refus muet se lit comme une panne.

    Les 40 refus preexistants du depot sont des `HttpResponse(status=403)`
    nus — page blanche. La page de C-1 nomme le droit requis et DERIVE de
    `ROLE_APP_PERMISSIONS` les roles qui le detiennent."""
    client, _ = _client_pour("caissier", "c1-page@example.com")
    contenu = client.get("/accounting/").content.decode()
    assert "accounting.view_accmove" in contenu
    assert "comptable" in contenu, "la page ne dit pas a quel role s'adresser"
    assert "Accès refusé" in contenu or "Acc&#xE8;s refus&#xE9;" in contenu


def test_a_screen_never_offers_an_action_the_guard_will_refuse() -> None:
    """C-1d — l'ecran cesse de proposer ce qu'il refusera.

    Le cas n'est pas exotique, c'est le plus courant : `direction` detient
    `view` et `change` sur les quatre modules mais **pas `add`** (mesure
    directe de `ROLE_APP_PERMISSIONS`). Sans ce volet, un dirigeant voit
    « Nouveau devis », clique, et recoit un refus — l'ecran lui a promis
    une action que la garde lui interdit.

    On eprouve avec `controleur_gestion`, qui n'a que `view` sur `sales` :
    la liste doit se rendre, et ne proposer aucune creation. `direction`
    ferait le meme office mais exige un enrolement MFA."""
    client, _ = _client_pour("controleur_gestion", "c1-boutons@example.com")
    contenu = client.get("/sales/").content.decode()
    assert "Nouveau devis" not in contenu, (
        "L'ecran propose la creation d'un devis a un role qui n'a pas le droit `add` : "
        "il promet une action que la garde refusera."
    )
    assert "/sales/new/" not in contenu

    contenu = client.get("/accounting/").content.decode()
    assert "Nouvelle facture" not in contenu
    assert "/accounting/new/" not in contenu


def test_a_role_that_may_create_still_sees_the_button() -> None:
    """La falsification du test precedent : une garde qui cacherait le
    bouton a TOUT LE MONDE le ferait passer sans rien prouver."""
    client, _ = _client_pour("magasinier", "c1-boutons-ok@example.com")
    contenu = client.get("/logistics/").content.decode()
    assert "/logistics/vehicles/new/" in contenu, (
        "`magasinier` detient `logistics.add_logvehicle` : le bouton de creation "
        "doit lui rester visible."
    )
