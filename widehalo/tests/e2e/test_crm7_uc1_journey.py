"""CRM-7 — le parcours UC1, chronométré et compté en clics.

Le critère : « Le parcours UC1 est réalisable en moins de 90 secondes et en
moins de 12 clics. » UC1, lui, est défini plus haut dans le même cahier :
« Qualifier un prospect entrant et planifier une relance » — condition de
sortie : « **Opportunité créée, rattachée à une société, avec une activité
planifiée.** »

**Il ne manquait pas un chronomètre : le parcours était IMPOSSIBLE**, et
c'est le même constat que SAL-1 avait fait pour le devis au clavier. La
troisième condition de sortie — « avec une activité planifiée » — ne
pouvait être atteinte par aucune surface du produit :

- `CrmActivity.due_at` existe depuis la migration `crm/0002` ;
- `services.activities.log_activity` l'accepte en paramètre ;
- `services.public.count_overdue_follow_ups` et la tuile « relances en
  retard » (CRM-4) le LISENT ;
- et **rien ne l'écrivait**, sauf `seed_crm`. Ni le formulaire d'activité
  de la fiche, qui n'avait pas de champ d'échéance, ni l'endpoint
  `POST /crm/leads/{id}/activities`, qui ne le transmettait pas.

Une activité enregistrée depuis l'écran était donc toujours une activité
DÉJÀ FAITE. Chez un client, la tuile des relances en retard ne pouvait rien
afficher — jamais — puisque aucune relance n'avait jamais d'échéance.

`test_crm_lead_journey` (dans `test_module_journeys.py`) existait, mais il
remplit un seul champ, ne rattache aucune société, ne planifie rien, ne
chronomètre rien et ne compte aucun clic. Il vérifiait qu'un écran répond,
pas qu'un parcours aboutit.

**Compter les clics n'est pas décoratif.** « Moins de 12 clics » est la
moitié du critère, et c'est celle qui se dégrade en silence : un champ
déplacé derrière un onglet, une confirmation ajoutée, et le parcours passe
de 8 à 14 clics sans qu'aucun test ne bouge. Le compteur ci-dessous
enregistre chaque clic que le test lui-même effectue — c'est une mesure
plancher honnête du parcours minimal, pas une simulation d'utilisateur.
"""

from __future__ import annotations

import time

import pytest
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmActivity, CrmLead, CrmPipeline, CrmStage
from apps.partners.models import Partner

pytestmark = pytest.mark.playwright

#: Les deux moitiés du critère, telles quelles.
UC1_BUDGET_SECONDES = 90
UC1_BUDGET_CLICS = 12

#: La recherche de société est déclenchée par `hx-trigger="keyup changed
#: delay:300ms"` : une frappe programme un échange qui peut REMPLACER la
#: liste sous le curseur. Même attente explicite que dans
#: `test_sal1_keyboard_quotation.py`, et pour la même raison.
_HTMX_DEBOUNCE_MS = 700


class ClickCounter:
    """Compte les clics du parcours. Un compteur, pas un espion.

    Il n'intercepte pas `page.click` par monkeypatch : le test appelle
    `clic()` explicitement, si bien que le nombre affiché est celui que le
    lecteur du test peut vérifier en comptant les appels dans le corps du
    test. Un compteur qu'on ne peut pas auditer à l'œil ne prouverait
    rien."""

    def __init__(self, page) -> None:
        self._page = page
        self.total = 0

    def clic(self, selecteur: str) -> None:
        self._page.click(selecteur)
        self.total += 1


@pytest.fixture
def uc1_context(logged_in_page, live_server, e2e_tenant_and_user):
    """Le strict nécessaire : une société à rattacher, un tunnel avec une
    étape. Rien de plus — UC1 part d'un prospect entrant, pas d'un jeu de
    données préparé."""
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )
        Partner.objects.create(tenant=tenant, name="Zafy Textile SARL", nif="1122334455")
    return logged_in_page, live_server, tenant


def _choisir_la_societe(page, compteur: ClickCounter) -> None:
    page.focus("#partner-picker-search-partner_id")
    page.keyboard.type("Zafy")
    page.wait_for_selector(".wh-partner-picker-option")
    page.wait_for_timeout(_HTMX_DEBOUNCE_MS)
    page.wait_for_selector(".wh-partner-picker-option")
    compteur.clic(".wh-partner-picker-option")


def test_uc1_is_completable_within_its_budget(uc1_context) -> None:
    """LE critère, de bout en bout : opportunité créée, rattachée à une
    société, avec une activité planifiée — chronométrée et comptée."""
    page, live_server, tenant = uc1_context
    compteur = ClickCounter(page)
    depart = time.perf_counter()

    # 1. Qualifier le prospect entrant.
    page.goto(f"{live_server.url}/crm/new/")
    page.wait_for_selector("#partner-picker-search-partner_id")
    page.fill("#name", "Prospect entrant Playwright")
    _choisir_la_societe(page, compteur)
    compteur.clic("#main-content button[type=submit]")
    page.wait_for_url(lambda url: "/crm/new/" not in url)

    # 2. Planifier la relance.
    page.select_option("#activity_type", "follow_up")
    page.fill("#activity_subject", "Rappeler pour qualifier le besoin")
    page.fill("#activity_due_at", "2026-12-15T09:00")
    compteur.clic("form:has(#activity_due_at) button[type=submit]")
    page.wait_for_selector("#activity_due_at")

    ecoule = time.perf_counter() - depart

    with use_tenant(tenant.id):
        piste = CrmLead.objects.get(name="Prospect entrant Playwright")
        assert piste.partner_id is not None, (
            "UC1 exige une opportunité RATTACHÉE À UNE SOCIÉTÉ ; celle-ci n'a pas de tiers."
        )
        relance = CrmActivity.objects.get(lead=piste)
        assert relance.due_at is not None, (
            "UC1 exige une activité PLANIFIÉE ; celle-ci n'a pas d'échéance — "
            "l'écran a de nouveau enregistré une activité déjà faite."
        )
        assert relance.done_at is None
        assert relance.activity_type == CrmActivity.TYPE_FOLLOW_UP

    assert ecoule < UC1_BUDGET_SECONDES, (
        f"UC1 parcouru en {ecoule:.1f} s (budget {UC1_BUDGET_SECONDES} s)"
    )
    assert compteur.total < UC1_BUDGET_CLICS, (
        f"UC1 parcouru en {compteur.total} clics (budget {UC1_BUDGET_CLICS})"
    )


def test_an_activity_without_a_due_date_is_still_a_past_one(uc1_context) -> None:
    """La contrepartie, et elle compte : rendre l'échéance obligatoire
    casserait l'autre usage du même formulaire — consigner un appel qui
    vient d'avoir lieu. Les deux doivent tenir sur la même surface."""
    page, live_server, tenant = uc1_context

    page.goto(f"{live_server.url}/crm/new/")
    page.wait_for_selector("#partner-picker-search-partner_id")
    page.fill("#name", "Prospect déjà appelé")
    page.click("#main-content button[type=submit]")
    page.wait_for_url(lambda url: "/crm/new/" not in url)

    page.select_option("#activity_type", "call")
    page.fill("#activity_subject", "Appel entrant reçu")
    page.click("form:has(#activity_due_at) button[type=submit]")
    page.wait_for_selector("#activity_due_at")

    with use_tenant(tenant.id):
        piste = CrmLead.objects.get(name="Prospect déjà appelé")
        activite = CrmActivity.objects.get(lead=piste)
        assert activite.due_at is None
        assert activite.subject == "Appel entrant reçu"


def test_the_timeline_distinguishes_a_planned_follow_up_from_a_past_activity(
    uc1_context,
) -> None:
    """Une chronologie qui affiche la date de CRÉATION pour tout est
    trompeuse : une relance prévue dans trois semaines s'y lisait comme une
    activité d'aujourd'hui. C'était le cas avant ce lot."""
    page, live_server, tenant = uc1_context

    page.goto(f"{live_server.url}/crm/new/")
    page.wait_for_selector("#partner-picker-search-partner_id")
    page.fill("#name", "Prospect chronologie")
    page.click("#main-content button[type=submit]")
    page.wait_for_url(lambda url: "/crm/new/" not in url)

    page.select_option("#activity_type", "follow_up")
    page.fill("#activity_subject", "Relance à trois semaines")
    page.fill("#activity_due_at", "2026-12-15T09:00")
    page.click("form:has(#activity_due_at) button[type=submit]")
    page.wait_for_selector("#activity_due_at")

    corps = page.content()
    assert "15/12/2026" in corps, (
        "La chronologie n'affiche pas l'échéance de la relance : elle est "
        "présentée comme une activité déjà réalisée."
    )
