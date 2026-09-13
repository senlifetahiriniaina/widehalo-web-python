"""ACC-3 (Phase 1, UC4) — une ecriture de quatre lignes se saisit ENTIEREMENT au
clavier, avec proposition de contrepartie et controle d'equilibre en continu.

Le critere, mot pour mot (cahier Phase 1, l.873) : « La saisie d'une ecriture
de 4 lignes est realisable entierement au clavier (parcours UC4), avec
proposition de contrepartie et controle d'equilibre en continu. »

**Ce que ce fichier prouve, et pourquoi il manquait.** L'audit classait ACC-3
🟡 : « le parcours clavier integral et l'affichage de l'equilibre en continu
n'ont pas ete verifies cote gabarit ». La 0.1.8 puis la 0.1.9 le disaient
encore : « ACC-3 attend toujours son parcours clavier chronometre ». Le
service etait garde (une ecriture VIDE ne consomme plus un numero legal,
cf. `test_acc3_empty_entry.py`) ; c'est la MESURE du parcours qui manquait.
SAL-1 et CRM-7 avaient la leur ; ACC-3 non.

**Ce test n'utilise JAMAIS la souris** — aucun `page.click`, uniquement
`page.focus` et `page.keyboard`. C'est la seule facon de prouver ce que le
critere demande. Meme discipline que `test_sal1_keyboard_quotation.py`.

**La contrepartie proposee est une CO-OCCURRENCE, pas une regle** :
`suggest_counterpart_account` rend le compte le plus souvent associe sur
une meme piece, et `None` sans historique. Sur une societe vierge il n'y a
donc RIEN a proposer — et une assertion « le selecteur porte une valeur »
passerait quand meme, parce qu'un `<select required>` selectionne son
premier `<option>` par defaut. La fixture amorce donc UNE ecriture
411 <-> 701 ; apres une ligne au debit sur 411, le selecteur doit arriver
sur 701000. Sans le mecanisme, il resterait sur 411000 : c'est la seule
assertion qui prouve la proposition.

**La date est GARDEE telle que proposee, jamais frappee — mesure, pas
prefere.** Un `<input type="date">` se saisit par segments dans l'ordre
de la locale du navigateur, et le Chromium sans tete de Playwright ne suit
pas `locale` : sous `fr-FR`, « 15012026 » a produit `2026-12-01`. Pire,
apres une frappe dans ce champ, Entree sur le bouton de soumission ne
soumettait plus rien (deux passes, aucune requete emise) ; le champ laisse
a sa valeur proposee, la meme Entree soumet et redirige. La vue propose la
date du jour ; l'utilisateur clavier qui la juge bonne la traverse — c'est
le parcours UC4, et il est independant de la locale.
"""

from __future__ import annotations

import calendar
import datetime as dt
import time
from decimal import Decimal

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.playwright

# Le critere ne fixe aucun temps ; UC4 en est la mesure. Le seuil est large a
# dessein — comme pour SAL-1, il n'est pas la pour chronometrer une
# performance mais pour attraper une regression qui rendrait le parcours
# impraticable (un champ devenu inaccessible au clavier, un bouton qui
# disparait, un rechargement qui perd le focus).
KEYBOARD_JOURNEY_BUDGET_SECONDS = 60


@pytest.fixture
def quick_entry_page(logged_in_page, live_server, e2e_tenant_and_user):
    """Une societe avec un exercice ouvert, un journal, deux comptes, et UNE
    ecriture d'historique 411 <-> 701 pour que la contrepartie ait quelque
    chose a proposer — puis l'ecran de saisie rapide."""
    tenant, _user = e2e_tenant_and_user
    # La vue propose la date du JOUR : l'exercice et la periode ouverts
    # doivent la contenir, quel que soit le jour ou ce test tourne.
    aujourd_hui = dt.date.today()
    premier = aujourd_hui.replace(day=1)
    dernier = aujourd_hui.replace(day=calendar.monthrange(aujourd_hui.year, aujourd_hui.month)[1])
    with use_tenant(tenant.id):
        exercice = AccFiscalYear.objects.create(
            tenant=tenant,
            code=f"FY{aujourd_hui.year}",
            date_start=dt.date(aujourd_hui.year, 1, 1),
            date_end=dt.date(aujourd_hui.year, 12, 31),
        )
        periode = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=exercice,
            code=premier.strftime("%Y-%m"),
            date_start=premier,
            date_end=dernier,
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        clients = AccAccount.objects.create(
            tenant=tenant,
            code="411000",
            name="Clients",
            account_class="4",
            type=AccAccount.TYPE_RECEIVABLE,
        )
        ventes = AccAccount.objects.create(
            tenant=tenant,
            code="701000",
            name="Ventes",
            account_class="7",
            type=AccAccount.TYPE_INCOME,
        )
        # L'historique dont la suggestion apprend : une piece ou 411 et 701
        # cohabitent. Un brouillon suffit — `suggest_counterpart_account`
        # compte « toutes ecritures confondues (brouillon ou publiee) ».
        historique = create_draft_move(
            tenant=tenant,
            journal=journal,
            period=periode,
            date=aujourd_hui,
            narration="Historique pour la contrepartie",
        )
        add_line(historique, account=clients, debit=Decimal("100"))
        add_line(historique, account=ventes, credit=Decimal("100"))

    page = logged_in_page
    page.goto(f"{live_server.url}/accounting/quick-entry/new/")
    page.wait_for_selector("#journal_id")
    return page, tenant


def _start_header_at_the_keyboard(page) -> None:
    """Journal, periode et date arrivent PRE-REMPLIS (defaut de la vue) : un
    utilisateur clavier les traverse sans rien frapper. `page.focus` n'est
    pas la souris — c'est le deplacement de focus, meme discipline que
    SAL-1 ; un Tab a travers un `<input type="date">` traverse ses trois
    segments un a un, ce qui rendrait le compte de Tab dependant du
    navigateur (cf. docstring du module sur la date)."""
    page.focus("#journal_id")
    page.keyboard.press("Tab")  # -> #period_id, deja selectionne
    page.focus("#narration")
    page.keyboard.type("Vente au comptant")
    page.focus("#main-content button[type=submit]")
    page.keyboard.press("Enter")
    # `**/quick-entry/**` serait satisfait par `/quick-entry/new/` lui-meme :
    # on attend explicitement d'avoir quitte le formulaire d'en-tete.
    page.wait_for_url(lambda url: "/quick-entry/new/" not in url)
    page.wait_for_selector("#account_id")


def _selected_account_text(page) -> str:
    """Le texte de l'option selectionnee du compte — lu sans le toucher."""
    return page.evaluate(
        "() => (document.querySelector('#account_id option:checked') || {}).textContent || ''"
    )


def _add_line_at_the_keyboard(page, *, account_code: str, debit: str, credit: str) -> None:
    """Une ligne, sans souris. Le compte se choisit par SAISIE ANTICIPEE dans
    le `<select>` (Chromium selectionne l'option dont le texte commence par
    les caracteres frappes) — c'est ce qu'un comptable fait au clavier.
    Entree dans un champ du formulaire le soumet (soumission implicite)."""
    page.focus("#account_id")
    page.keyboard.type(account_code)
    page.focus("#debit")
    page.keyboard.press("Control+A")
    page.keyboard.type(debit)
    page.focus("#credit")
    page.keyboard.press("Control+A")
    page.keyboard.type(credit)
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#account_id")


def test_the_header_starts_at_the_keyboard(quick_entry_page) -> None:
    """L'en-tete : journal, periode, date, libelle, demarrage — sans souris."""
    page, tenant = quick_entry_page
    _start_header_at_the_keyboard(page)

    assert "/accounting/quick-entry/" in page.url
    with use_tenant(tenant.id):
        assert AccMove.objects.filter(narration="Vente au comptant").exists(), (
            "aucun brouillon n'a ete cree par le parcours clavier"
        )


def test_the_counterpart_is_proposed_and_the_balance_is_read_continuously(
    quick_entry_page,
) -> None:
    """Le coeur du critere : contrepartie proposee, equilibre lu en continu,
    quatre lignes. Aucun `page.click`."""
    page, _tenant = quick_entry_page
    _start_header_at_the_keyboard(page)

    # Ligne 1, au debit sur 411. Desequilibree par construction : le badge
    # ne doit PAS pretendre l'equilibre.
    _add_line_at_the_keyboard(page, account_code="411", debit="1000", credit="0")
    assert "Équilibrée" not in page.text_content("#main-content"), (
        "l'ecran declare « Equilibree » une ecriture a une seule ligne au debit"
    )

    # PROPOSITION DE CONTREPARTIE : apres un debit sur 411, le selecteur doit
    # arriver deja positionne sur 701 — le compte que l'historique associe
    # a 411. Sans le mecanisme, il resterait sur la premiere option (411).
    assert _selected_account_text(page).startswith("701000"), (
        f"contrepartie non proposee : le selecteur porte {_selected_account_text(page)!r}"
    )

    # Lignes 2 a 4 — quatre lignes signifiantes, equilibrees a la fin :
    # 411 D 1000 + 411 D 300 = 1300 ; 701 C 600 + 701 C 700 = 1300.
    _add_line_at_the_keyboard(page, account_code="411", debit="300", credit="0")
    _add_line_at_the_keyboard(page, account_code="701", debit="0", credit="600")
    assert "Équilibrée" not in page.text_content("#main-content"), (
        "l'ecran declare « Equilibree » a 1300 D / 600 C"
    )
    _add_line_at_the_keyboard(page, account_code="701", debit="0", credit="700")

    # EQUILIBRE EN CONTINU : 1300 D = 1300 C -> le badge apparait maintenant,
    # sans qu'on ait rien demande.
    page.wait_for_selector("text=Équilibrée")


def test_the_entry_is_posted_at_the_keyboard_within_budget(quick_entry_page) -> None:
    """Bout en bout, chronometre : en-tete, quatre lignes, publication.
    L'etat se lit en base, la ou il est ecrit."""
    page, tenant = quick_entry_page
    started = time.perf_counter()

    _start_header_at_the_keyboard(page)
    _add_line_at_the_keyboard(page, account_code="411", debit="700", credit="0")
    _add_line_at_the_keyboard(page, account_code="411", debit="300", credit="0")
    _add_line_at_the_keyboard(page, account_code="701", debit="0", credit="600")
    _add_line_at_the_keyboard(page, account_code="701", debit="0", credit="400")
    page.wait_for_selector("text=Équilibrée")

    page.focus("button[name=action][value=post]")
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")

    elapsed = time.perf_counter() - started
    assert elapsed < KEYBOARD_JOURNEY_BUDGET_SECONDS, (
        f"parcours clavier en {elapsed:.1f} s (budget {KEYBOARD_JOURNEY_BUDGET_SECONDS} s)"
    )

    with use_tenant(tenant.id):
        piece = AccMove.objects.get(narration="Vente au comptant")
        assert piece.state == AccMove.STATE_POSTED, "l'ecriture n'est pas publiee"
        assert piece.lines.count() == 4
        assert piece.reference, "une ecriture publiee doit porter sa reference (RG-ACC-3)"
