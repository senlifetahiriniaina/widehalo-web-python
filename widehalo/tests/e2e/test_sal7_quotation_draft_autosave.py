"""SAL-7 (L5, reliquat) — le brouillon de devis survit à la fermeture de
l'onglet, et à une erreur de validation.

**Ce qui manquait.** `lineItems()` gardait ses lignes en mémoire Alpine et
`init()` repartait d'une ligne vierge à chaque chargement : un onglet fermé,
un rechargement, une coupure, et vingt lignes saisies à la main étaient
perdues. `offline_queue.js` ne couvre pas ce cas — il n'intercepte qu'à la
**soumission**, et seulement **hors ligne**. Aucun `beforeunload`, aucun
identifiant stable de brouillon nulle part dans le dépôt.

**Et il y avait pire, en ligne.** `apps/sales/views.py::quotation_create`
re-rend le formulaire **vide** après une erreur de validation : aucun
`value=` dans le gabarit, `lines` réinitialisé. Une date mal saisie suffisait
donc déjà à tout perdre, sans la moindre panne réseau. C'est le second test
ci-dessous, et c'est celui qui décrit le cas que les utilisateurs
rencontrent réellement le plus souvent.

Patron repris de `test_kanban_degraded_network.py` (lecture de
`localStorage` par `page.evaluate`) et de `test_sal1_keyboard_quotation.py`
pour l'entrée sur `/sales/new/` — dont la fixture ne remplissait **aucune
ligne**, ce qui est précisément ce qu'il fallait ajouter.
"""

from __future__ import annotations

import re

import pytest
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner

pytestmark = pytest.mark.playwright

_DRAFT_KEY = "wh-draft-quotation"


@pytest.fixture
def quotation_page(logged_in_page, live_server, e2e_tenant_and_user):
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Zafy Textile SARL", nif="1122334455")

    page = logged_in_page
    page.goto(f"{live_server.url}/sales/new/")
    page.wait_for_selector("#partner-picker-search-partner_id")
    return page, tenant, live_server


def _fill_two_lines(page) -> None:
    """Remplit deux lignes — la fixture héritée de SAL-1 n'en remplissait
    aucune, si bien qu'aucun test du dépôt n'avait jamais eu de saisie à
    perdre."""
    page.fill("#contact", "Mme Rasoa")
    page.fill("input[name='description_0']", "Coupe et assemblage")
    page.fill("input[name='qty_0']", "12")
    page.fill("input[name='unit_price_0']", "45000")
    page.click("form[data-submit-failed] >> text=Ajouter une ligne")
    page.wait_for_selector("input[name='description_1']")
    page.fill("input[name='description_1']", "Broderie main")
    page.fill("input[name='qty_1']", "3")
    page.fill("input[name='unit_price_1']", "80000")


def _draft(page):
    return page.evaluate(
        "(key) => { try { return JSON.parse(window.localStorage.getItem(key)); }"
        " catch (e) { return null; } }",
        _DRAFT_KEY,
    )


def test_the_draft_is_saved_while_typing(quotation_page) -> None:
    """Sauvegarde à la frappe, sans aucun geste de l'utilisateur : un
    brouillon qu'il faut penser à enregistrer ne protège personne — celui
    qui y pense est déjà celui qui ne perd rien."""
    page, _tenant, _server = quotation_page
    assert _draft(page) is None, "Un brouillon existe avant toute saisie."

    _fill_two_lines(page)

    draft = _draft(page)
    assert draft is not None, "Rien n'est sauvegardé pendant la saisie."
    assert len(draft["lines"]) == 2
    assert draft["lines"][0]["description"] == "Coupe et assemblage"
    assert draft["lines"][1]["qty"] == "3"
    assert draft["fields"]["contact"] == "Mme Rasoa"
    # Le jeton CSRF est lié à la session : rejoué plus tard il serait
    # invalide, et le conserver serait un secret de session écrit dans le
    # stockage du navigateur sans raison.
    assert "csrfmiddlewaretoken" not in draft["fields"]

    # Les champs de LIGNE ne doivent pas être dupliqués dans `fields` : ils
    # sont déjà portés par `lines`, et à la restauration `_restoreFields`
    # les réécrirait dans le DOM par-dessus le rendu qu'Alpine vient de
    # produire depuis `lines` — deux sources pour une même valeur finissent
    # toujours par diverger.
    #
    # Cette assertion a été AJOUTÉE après coup : la falsification a montré
    # que sans elle le test restait vert même en désactivant complètement
    # `_isLineField`. Le garde-fou existait, rien ne le vérifiait.
    duplicated = [
        name
        for name in draft["fields"]
        if name.startswith(("description_", "qty_", "unit_price_", "variant_id_"))
    ]
    assert not duplicated, f"Champs de ligne dupliqués dans le brouillon : {duplicated}"


def test_the_draft_survives_closing_the_tab(quotation_page) -> None:
    """Le cœur du critère. `init()` repartait d'une ligne vierge : à ce
    stade, tout était perdu."""
    page, _tenant, server = quotation_page
    _fill_two_lines(page)

    page.goto(f"{server.url}/sales/")
    page.goto(f"{server.url}/sales/new/")
    page.wait_for_selector("input[name='description_1']")

    assert page.input_value("input[name='description_0']") == "Coupe et assemblage"
    assert page.input_value("input[name='qty_0']") == "12"
    assert page.input_value("input[name='description_1']") == "Broderie main"
    assert page.input_value("#contact") == "Mme Rasoa"
    # La restauration est DITE, jamais silencieuse : un formulaire
    # pré-rempli sans explication laisse croire à un devis déjà enregistré.
    #
    # VISIBILITÉ, jamais `in page.content()` : la bannière vit dans un
    # `<template x-if>`, et le contenu d'un `<template>` figure dans le HTML
    # sérialisé même quand Alpine ne le rend pas. Écrite avec `content()`,
    # cette assertion était vraie dans TOUS les cas — elle passait sans rien
    # prouver, et c'est le test frère (qui exige l'absence de bannière) qui
    # l'a démasquée en échouant pour cette même raison.
    assert page.locator("form[data-submit-failed] >> text=Brouillon restauré").is_visible()


def test_a_validation_error_no_longer_empties_the_form(quotation_page) -> None:
    """Le défaut le plus fréquent, et il n'a rien à voir avec le réseau :
    la vue re-rend le formulaire VIDE après une erreur. Soumis sans client,
    `uuid.UUID("")` lève, la page revient avec son erreur — et emportait
    toute la saisie."""
    page, _tenant, _server = quotation_page
    _fill_two_lines(page)

    page.click("form[data-submit-failed] button[type='submit']")
    page.wait_for_selector(".form-error")

    assert page.input_value("input[name='description_0']") == "Coupe et assemblage"
    assert page.input_value("input[name='unit_price_1']") == "80000"
    assert page.input_value("#contact") == "Mme Rasoa"


def test_the_draft_can_be_discarded_on_purpose(quotation_page) -> None:
    """Un brouillon qu'on ne peut pas jeter devient un piège : l'ancienne
    saisie reviendrait à chaque « Nouveau devis »."""
    page, _tenant, server = quotation_page
    _fill_two_lines(page)

    page.goto(f"{server.url}/sales/new/")
    page.wait_for_selector("input[name='description_1']")
    page.click("form[data-submit-failed] >> text=Repartir de zéro")

    assert page.input_value("input[name='description_0']") == ""
    assert page.input_value("#contact") == ""
    assert _draft(page) is None

    page.goto(f"{server.url}/sales/new/")
    page.wait_for_selector("input[name='description_0']")
    assert page.input_value("input[name='description_0']") == ""


def test_a_successful_creation_does_not_leave_its_draft_behind(quotation_page) -> None:
    """La contrepartie du test précédent. En cas de succès le navigateur
    part vers la fiche : cette page n'est jamais rechargée, donc rien ne
    purge le brouillon sur place. S'il n'était pas marqué, le devis qu'on
    vient d'enregistrer reviendrait au prochain « Nouveau devis » — et
    quelqu'un le saisirait deux fois."""
    page, _tenant, server = quotation_page

    # Le parcours clavier est deja couvert par `test_sal1_keyboard_quotation`.
    # Ici on veut seulement un devis valide : on clique l'option, puis on
    # VERIFIE que le champ cache porte bien un identifiant — sans quoi le
    # POST echouerait et ce test parlerait d'autre chose que de son sujet.
    page.focus("#partner-picker-search-partner_id")
    page.keyboard.type("Zafy")
    page.wait_for_selector(".wh-partner-picker-option")
    page.click(".wh-partner-picker-option")
    page.wait_for_function('() => document.querySelector("#partner_id").value.length > 0')

    _fill_two_lines(page)
    page.click("form[data-submit-failed] button[type='submit']")
    # La fiche est `/sales/<uuid>/`, jamais `/sales/quotations/<uuid>/`.
    page.wait_for_url(re.compile(r"/sales/[0-9a-f-]{36}/$"))

    page.goto(f"{server.url}/sales/new/")
    page.wait_for_selector("input[name='description_0']")

    assert page.input_value("input[name='description_0']") == "", (
        "Le devis enregistré revient comme brouillon : il serait saisi deux fois."
    )
    assert not page.locator("form[data-submit-failed] >> text=Brouillon restauré").is_visible()


def test_the_order_screen_keeps_its_own_draft(quotation_page) -> None:
    """Les deux écrans partagent `lineItems()`. Une clé commune ferait
    apparaître les lignes d'un devis dans une commande de vente."""
    page, _tenant, server = quotation_page
    _fill_two_lines(page)

    page.goto(f"{server.url}/sales/orders/new/")
    page.wait_for_selector("input[name='description_0']")

    assert page.input_value("input[name='description_0']") == "", (
        "Le brouillon du devis a fuité dans l'écran de commande."
    )
