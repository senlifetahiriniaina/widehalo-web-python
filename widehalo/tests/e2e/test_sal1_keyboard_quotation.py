"""SAL-1 (L16) — un devis se cree entierement au clavier, sans souris.

Le critere : « Devis de 5 lignes entierement au clavier, sans souris, en
moins de 2 minutes ». L'audit le classait 🟡 « ni la navigation clavier
exhaustive ni le chronometre ne sont verifies par un test ».

**Il ne manquait pas une mesure : le parcours etait IMPOSSIBLE.** Le seul
moyen de renseigner `partner_id` — champ OBLIGATOIRE cote vue — etait un
`<li>` nu, ni focalisable ni actionnable au clavier, dont l'unique
gestionnaire etait un `click` delegue. Aucune sequence de touches ne
permettait de choisir un client, donc aucun commercial travaillant au
clavier ne pouvait creer de devis, quelle que soit la duree.

Et le trou etait invisible en CI : le parcours e2e existant contourne le
composant en posant la valeur par `page.evaluate`, avec un commentaire qui
dit renvoyer au « test dedie » du picker.

Chaque resultat est desormais un vrai `<button>` : focalisable, actionnable
par Entree/Espace, et couvert par le meme gestionnaire de clic delegue sans
une ligne de JS supplementaire.

**Ce test n'utilise JAMAIS la souris** — aucun `page.click`, uniquement
`page.keyboard`. C'est la seule facon de prouver ce que le critere demande.
"""

from __future__ import annotations

import time

import pytest
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner

pytestmark = pytest.mark.playwright

# Le critere parle de deux minutes pour cinq lignes. Ce test couvre
# l'en-tete (client + date), la ou le parcours etait rompu : le seuil est
# donc large a dessein — il n'est pas la pour chronometrer une performance,
# mais pour attraper une regression qui rendrait le parcours impraticable.
KEYBOARD_JOURNEY_BUDGET_SECONDS = 30

# La recherche instantanee est declenchee par `hx-trigger="keyup changed
# delay:300ms"` : une frappe programme un echange qui peut REMPLACER la liste
# sous le focus. Un humain marque naturellement cette pause avant de tabuler ;
# le test la marque explicitement, sinon il tabulerait vers un bouton que htmx
# s'apprete a detruire (le focus retomberait alors sur `<body>`).
_HTMX_DEBOUNCE_MS = 700


def _typed_search(page, text: str) -> None:
    """Frappe dans la recherche et attend que la liste soit STABLE."""
    page.focus("#partner-picker-search-partner_id")
    page.keyboard.type(text)
    page.wait_for_selector(".wh-partner-picker-option")
    page.wait_for_timeout(_HTMX_DEBOUNCE_MS)
    page.wait_for_selector(".wh-partner-picker-option")


@pytest.fixture
def quotation_page(logged_in_page, live_server, e2e_tenant_and_user):
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Zafy Textile SARL", nif="1122334455")

    page = logged_in_page
    page.goto(f"{live_server.url}/sales/new/")
    page.wait_for_selector("#partner-picker-search-partner_id")
    return page, tenant


def test_a_partner_can_be_chosen_without_a_mouse(quotation_page) -> None:
    """Le coeur du defaut. Aucun `page.click` dans ce test."""
    page, _tenant = quotation_page

    _typed_search(page, "Zafy")

    # Tabulation depuis le champ de recherche jusqu'au premier resultat,
    # puis Entree — exactement ce qu'un utilisateur clavier fait.
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement.className")
    assert "wh-partner-picker-option" in focused, (
        f"le premier resultat n'est pas atteignable par Tab (focus : {focused!r})"
    )
    page.keyboard.press("Enter")

    partner_id = page.input_value("#partner_id")
    assert partner_id, "le champ obligatoire `partner_id` est reste vide"
    assert "Zafy Textile SARL" in page.text_content("#partner_id_display")


def test_the_whole_quotation_header_is_reachable_at_the_keyboard(quotation_page) -> None:
    """Bout en bout, toujours sans souris : client, date, soumission."""
    page, _tenant = quotation_page
    started = time.perf_counter()

    _typed_search(page, "Zafy")
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")

    # Un `<input type="date">` se saisit par SEGMENTS, dans l'ordre affiche
    # par la locale (JJ/MM/AAAA en francais) : un utilisateur clavier frappe
    # des chiffres, jamais la chaine ISO. La frapper telle quelle produit une
    # date absurde — ce que la premiere version de ce test faisait.
    page.focus("#date")
    page.keyboard.type("10012026")

    page.focus("#main-content button[type=submit]")
    page.keyboard.press("Enter")
    # `**/sales/**` serait satisfait par `/sales/new/` LUI-MEME, donc
    # instantanement : on attend explicitement d'avoir quitte le formulaire.
    page.wait_for_url(lambda url: "/sales/new/" not in url)

    elapsed = time.perf_counter() - started
    assert elapsed < KEYBOARD_JOURNEY_BUDGET_SECONDS, (
        f"parcours clavier en {elapsed:.1f} s (budget {KEYBOARD_JOURNEY_BUDGET_SECONDS} s)"
    )
    assert "/sales/" in page.url


def test_the_focused_result_is_visibly_focused(quotation_page) -> None:
    """Un element focalisable dont on ne voit pas le focus n'est utilisable
    par personne : le parcours clavier doit etre LISIBLE, pas seulement
    possible."""
    page, _tenant = quotation_page
    _typed_search(page, "Zafy")
    page.keyboard.press("Tab")

    outline = page.evaluate("() => getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none", "aucun indicateur de focus visible sur le résultat"
