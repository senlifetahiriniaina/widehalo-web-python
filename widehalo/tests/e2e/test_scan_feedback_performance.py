"""STK-10 (L12-5) — le retour visuel de scan sous 300 ms, mesure.

Critere : « Le retour visuel apres un scan est affiche en moins de 300 ms,
y compris en mode degrade. »

**Le seuil n'existait nulle part dans le code** — uniquement dans le
cahier (l. 422 et 672) et dans un commentaire de `stocks/tw-scan.html` qui
ne le chiffrait pas. La conception, elle, est bonne : `justScanned = true`
est pose SYNCHRONE dans `onScanSubmit`, avant tout aller-retour reseau.
Elle n'etait simplement jamais mesuree.

**Un defaut reel trouve en la mesurant.** `static/js/offline_queue.js::
showNotice` cherche `.wh-toast-container` et, faute de le trouver, retombe
sur un `window.alert()` BLOQUANT. Ce conteneur n'existait que dans
`base.html` : `stocks/tw-scan.html` et `tw-launchpad.html`, les deux
gabarits autonomes qui chargent la file hors-ligne, n'en avaient aucun.
Chaque scan hors connexion ouvrait donc une boite de dialogue modale que
le magasinier devait fermer avant de scanner l'article suivant — sur
l'ecran precisement concu pour le mode degrade, et en contradiction
directe avec ce critere. Le conteneur vit desormais dans
`templates/cotton/shell.html` ; `test_the_offline_feedback_...` interdit
tout retour de la boite de dialogue.

**Deux mesures, parce qu'une seule ne prouverait rien.** Une mesure en
ligne sur un serveur local rapide ne distinguerait pas un retour client
d'un aller-retour reseau chanceux. Le second test coupe donc la reponse du
serveur : ce qui s'affiche malgre un serveur muet est necessairement pose
cote client, ce qui est exactement l'affirmation du critere.

Precedent de test de timing dans le depot :
`apps/quality/tests/test_recall_performance.py` (constante de seuil +
marqueur), dont la docstring dit etre « le premier test de ce type ».
"""

from __future__ import annotations

import time

import pytest
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.playwright

# Le seuil du cahier, ecrit une seule fois et nulle part ailleurs.
SCAN_FEEDBACK_THRESHOLD_MS = 300

_FEEDBACK = "text=✓ Enregistré"
_RECEIVE_FORM_SUBMIT = 'form[action*="scan/receive"] button[type=submit]'
_EAN13 = "3401579842317"


@pytest.fixture
def scan_page(logged_in_page, live_server, e2e_tenant_and_user):
    """Ecran magasinier reellement utilisable : sans entrepot, sans
    emplacement interne scannable et sans emplacement fournisseur, la vue
    ne rend tout simplement pas le formulaire de reception
    (`apps/stocks/views.py::scan_screen`)."""
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-E2E", name="Entrepot E2E")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="E2E-A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="E2E-FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )

    page = logged_in_page
    page.goto(
        f"{live_server.url}/stocks/scan/?warehouse_id={warehouse.id}&location_scan={internal.code}"
    )
    page.wait_for_selector(_RECEIVE_FORM_SUBMIT)
    return page


def _scan_and_measure(page) -> float:
    """Remplit et soumet un scan, renvoie le delai en millisecondes entre
    le clic et l'apparition du retour visuel.

    Le `timeout` de `wait_for_selector` est volontairement large : c'est
    l'assertion sur la mesure qui porte le seuil, pour qu'un echec affiche
    le chiffre reel plutot qu'un « timeout » muet."""
    page.fill('input[name="ean13"]', _EAN13)
    started = time.perf_counter()
    page.click(_RECEIVE_FORM_SUBMIT)
    page.wait_for_selector(_FEEDBACK, state="visible", timeout=5000)
    return (time.perf_counter() - started) * 1000


def test_the_offline_feedback_is_shown_under_the_threshold_and_never_as_a_dialog(
    scan_page,
) -> None:
    """Le mode degrade, celui pour lequel cet ecran existe.

    Hors ligne, `offline_queue.js` annule la soumission native : le retour
    visuel est donc reel et persistant (600 ms), pas un eclair avant
    navigation. La liste `dialogs` est la non-regression du defaut du
    `window.alert()` — un magasinier ne doit rien avoir a fermer entre deux
    articles."""
    page = scan_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    page.context.set_offline(True)
    try:
        elapsed_ms = _scan_and_measure(page)
    finally:
        page.context.set_offline(False)

    assert elapsed_ms < SCAN_FEEDBACK_THRESHOLD_MS, (
        f"retour visuel hors ligne en {elapsed_ms:.0f} ms "
        f"(seuil STK-10 : {SCAN_FEEDBACK_THRESHOLD_MS} ms)"
    )
    assert dialogs == [], f"boite de dialogue bloquante ouverte : {dialogs}"
    # La confirmation hors-ligne passe bien par un toast non bloquant.
    assert page.locator(".wh-toast-container .wh-toast").count() >= 1


def test_the_feedback_does_not_wait_for_the_server(scan_page) -> None:
    """L'affirmation exacte du critere : « independant de l'etat du
    reseau ».

    La requete de reception est coupee net. Ce qui s'affiche malgre un
    serveur qui ne repond jamais est necessairement pose cote client — une
    mesure en ligne ordinaire, sur un serveur local rapide, ne pourrait pas
    faire cette distinction."""
    page = scan_page
    # `"aborted"` et non l'echec par defaut : Chromium traite ERR_ABORTED
    # comme une navigation annulee et RESTE sur la page courante, la ou un
    # ERR_FAILED afficherait une page d'erreur qui remplacerait le document
    # — et donc le retour visuel qu'on cherche justement a observer.
    page.route("**/stocks/scan/receive/", lambda route: route.abort("aborted"))

    elapsed_ms = _scan_and_measure(page)

    assert elapsed_ms < SCAN_FEEDBACK_THRESHOLD_MS, (
        f"retour visuel en {elapsed_ms:.0f} ms alors que le serveur ne repond pas "
        f"(seuil STK-10 : {SCAN_FEEDBACK_THRESHOLD_MS} ms)"
    )


def test_an_empty_scan_shows_no_feedback_at_all(scan_page) -> None:
    """Le retour ne doit pas etre un reflexe aveugle : sans code-barres,
    `onScanSubmit` annule la soumission et n'affiche rien. Un « ✓
    Enregistré » sur un scan vide serait pire qu'un retour lent."""
    page = scan_page
    page.click(_RECEIVE_FORM_SUBMIT)

    assert page.locator(_FEEDBACK).is_visible() is False
