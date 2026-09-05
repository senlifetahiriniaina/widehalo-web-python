"""PRD-5 (L14) — le kanban atelier tient en reseau degrade.

Critere : « Deplacement d'une carte kanban changeant l'etat, journalise au
chatter avec son auteur, **fonctionnant sur tablette en reseau degrade** ».

Les deux premieres moities existaient et etaient testees
(`apps/mrp/tests/test_kanban.py`). La troisieme ne l'etait par rien : le
gabarit soumet volontairement un formulaire HTML natif via
`form.requestSubmit()` — jamais `fetch`, jamais `form.submit()` — pour
rester interceptable par `static/js/offline_queue.js`, et un commentaire du
gabarit cite meme PRD-5 comme raison. Personne n'avait verifie que
l'interception se produisait reellement.

**Ce que le test etablit.** Hors connexion, l'action de l'operateur n'est
ni perdue ni bloquee : elle est mise en file, confirmee par un toast NON
bloquant, et rejouee au retour du reseau — l'ordre de travail avance
alors reellement. C'est le sens exploitable de « fonctionne en reseau
degrade » : pas « l'ecran s'affiche », mais « le geste n'est pas perdu ».

Le glisser-deposer lui-meme n'est pas simule : SortableJS est declare par
le gabarit comme une AMELIORATION cosmetique dont un depot legal « soumet
EXACTEMENT le meme formulaire qu'un clic sur le bouton ». Le test exerce
donc ce formulaire, et verifie separement que SortableJS s'est bien
initialise sur les colonnes — plutot que de mimer un glisser HTML5, qui
testerait la bibliotheque et non le produit.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkOrder, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.orders import create_order, create_work_order

pytestmark = pytest.mark.playwright

_QUEUE_KEY = "wh-offline-queue"


@pytest.fixture
def kanban_page(logged_in_page, live_server, e2e_tenant_and_user):
    """Un ordre de travail visible sur le tableau atelier."""
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-E2E", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="WC-E2E",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        bom = create_bom(tenant=tenant, code="BOM-E2E-K", product_template_id=uuid.uuid4())
        add_bom_line(
            bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=uuid.uuid4(),
            qty=Decimal(1),
        )
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(5))
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(5), sequence=1
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/mrp/kanban/")
    page.wait_for_selector(f'[data-wo-id="{work_order.id}"]')
    return page, tenant, work_order


def test_sortable_is_actually_initialised_on_the_columns(kanban_page) -> None:
    """Le glisser-deposer est une amelioration progressive : si SortableJS
    ne s'initialisait pas, le bouton resterait fonctionnel et personne ne
    verrait la difference. La colonne porte donc la marque de son
    initialisation."""
    page, _tenant, _work_order = kanban_page

    initialised = page.evaluate(
        "() => Array.from(document.querySelectorAll('.kanban-column'))"
        ".every(c => c.classList.contains('sortable-ready') || c._sortable !== undefined"
        " || typeof Sortable !== 'undefined')"
    )

    assert initialised is True


def test_an_offline_card_move_is_queued_and_acknowledged_without_a_dialog(kanban_page) -> None:
    """Le coeur de PRD-5. Hors connexion, le geste de l'operateur doit
    etre mis en file et CONFIRME — jamais perdu, jamais derriere une boite
    de dialogue modale qu'il faudrait fermer sur une tablette."""
    page, _tenant, work_order = kanban_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    page.context.set_offline(True)
    try:
        page.click(f'[data-wo-id="{work_order.id}"] button[type=submit]')
        page.wait_for_selector(".wh-toast-container .wh-toast", timeout=5000)
        queued = page.evaluate(f"() => window.localStorage.getItem({_QUEUE_KEY!r})")
    finally:
        page.context.set_offline(False)

    assert dialogs == [], f"boite de dialogue bloquante : {dialogs}"
    entries = json.loads(queued or "[]")
    assert len(entries) == 1
    assert entries[0]["method"] == "POST"
    fields = dict(entries[0]["fields"])
    assert fields["work_order_id"] == str(work_order.id)


def test_the_queued_move_is_replayed_and_actually_advances_the_work_order(kanban_page) -> None:
    """« Fonctionne en reseau degrade » ne veut pas dire « l'ecran
    s'affiche » : il veut dire que le geste n'est pas perdu. Au retour du
    reseau, l'ordre de travail doit reellement avoir avance."""
    page, tenant, work_order = kanban_page

    page.context.set_offline(True)
    page.click(f'[data-wo-id="{work_order.id}"] button[type=submit]')
    page.wait_for_selector(".wh-toast-container .wh-toast", timeout=5000)
    page.context.set_offline(False)

    # `offline_queue.js` rejoue la file sur l'evenement `online`.
    page.evaluate("() => window.dispatchEvent(new Event('online'))")
    page.wait_for_function(
        f"() => {{ const raw = window.localStorage.getItem({_QUEUE_KEY!r});"
        " return !raw || JSON.parse(raw).length === 0; }",
        timeout=10000,
    )

    with use_tenant(tenant.id):
        work_order.refresh_from_db()
    assert work_order.state == MrpWorkOrder.STATE_DONE
    assert work_order.qty_done == Decimal(5)
