"""D-A — un bouton proposé par un écran produit un effet, ou dit pourquoi.

**Ce test existe parce que son prédécesseur trichait.**
`test_c4_prochaine_action.py::test_what_the_banner_posts_is_what_the_view_expects`
postait `{"action": "send"}` — une valeur écrite EN DUR dans le test. Il
vérifiait donc que la vue sait traiter « send », jamais que le bandeau
poste ce que la vue attend. Il passait au vert pendant que **dix boutons
sur les six fiches ne faisaient rien** : la fiche CRM postait
`action=<UUID d'étape>`, la commande postait `mark_invoiced` là où la vue
attend `invoice`, et la facture proposait cinq transitions qu'aucune
branche ne traite. La clause `else:` du `try` rendait la redirection, sans
erreur et sans effet.

La forme de ce test est donc la propriété elle-même : on ne décide de rien,
on **demande au registre ce qu'il propose**, on poste EXACTEMENT ça, et on
exige un effet observable. Le seul comportement interdit est le no-op
silencieux — un POST qui redirige sans avoir rien changé et sans rien dire.

Une action qui échoue pour une raison métier est un résultat ACCEPTABLE :
l'écran rend alors son message d'erreur. Ce qui ne l'est pas, c'est le
silence.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.next_steps import next_steps_for
from apps.core.tests.utils import grant_module_access, use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


def _client(tenant: Tenant, user: User) -> Client:
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


#: Les droits PROPRES a certaines actions d'ecran, hors du triplet
#: view/add/change. Mesure : le bandeau de la facture exige
#: `validate_accmove` et `cancel_accmove` (`apps/accounting/views.py:94-98`)
#: — un utilisateur qui ne les a pas ne DOIT pas se les voir proposer, et
#: c'est teste ailleurs ; ici on veut l'utilisateur qui peut agir.
_DROITS_PROPRES = ("validate_accmove", "cancel_accmove")


def _societe_et_utilisateur(code: str, courriel: str) -> tuple[Tenant, User]:
    from django.contrib.auth.models import Permission

    tenant = Tenant.objects.create(code=code, name=f"Societe {code}")
    user = User.objects.create_user(email=courriel, password="Str0ngPassw0rd!23")
    grant_module_access(user, "sales", "crm", "accounting", "logistics")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=_DROITS_PROPRES, content_type__app_label="accounting"
        )
    )
    return tenant, User.objects.get(pk=user.pk)  # cache de permissions vide


def _commande(tenant: Tenant, _user: User) -> Any:
    from apps.sales.services.orders import create_order

    with use_tenant(tenant.id):
        return create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())


def _opportunite(tenant: Tenant, user: User) -> Any:
    """`salesperson=user` n'est pas un detail de confort.

    Le CRM porte une portee par ENREGISTREMENT (N3) : `scope_leads_for_user`
    ne rend que les opportunites dont l'utilisateur est le vendeur assigne,
    et la vue repond **404** — pas 403 — hors de ce perimetre
    (`apps/crm/views.py:86-104`, choix documente). Une premiere version de
    ce test creait une opportunite sans vendeur et recevait 404 : le test
    etait faux, pas le code. Un commercial agit sur SES affaires."""
    from apps.crm.services.leads import create_lead_quick
    from apps.crm.services.pipelines import ensure_default_pipeline

    with use_tenant(tenant.id):
        ensure_default_pipeline(tenant)
        return create_lead_quick(tenant=tenant, name="Affaire à suivre", salesperson=user)


def _expedition(tenant: Tenant, _user: User) -> Any:
    from apps.logistics.services.shipments import create_shipment

    with use_tenant(tenant.id):
        return create_shipment(tenant=tenant, origin="Toamasina", destination="Antananarivo")


def _facture(tenant: Tenant, _user: User) -> Any:
    """Une facture client en brouillon, sous le seuil de double validation.

    Le montant compte : au-dessus de `DOUBLE_VALIDATION_THRESHOLD_MGA`,
    `validate_invoice` cree une demande d'approbation et leve — ce qui est
    un refus LEGITIME, pas un no-op, mais qui ne mesurerait plus ce que ce
    test surveille."""
    from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
    from apps.accounting.services.invoices import create_invoice

    with use_tenant(tenant.id):
        # `get_or_create` : ce constructeur est rappele pour CHAQUE etape
        # proposee, et le referentiel comptable est unique par societe.
        exercice, _ = AccFiscalYear.objects.get_or_create(
            tenant=tenant,
            code="2026",
            defaults={"date_start": dt.date(2026, 1, 1), "date_end": dt.date(2026, 12, 31)},
        )
        periode, _ = AccPeriod.objects.get_or_create(
            tenant=tenant,
            code="2026-01",
            defaults={
                "fiscal_year": exercice,
                "date_start": dt.date(2026, 1, 1),
                "date_end": dt.date(2026, 1, 31),
            },
        )
        journal, _ = AccJournal.objects.get_or_create(
            tenant=tenant,
            code="VTE",
            defaults={
                "name": "Ventes",
                "type": AccJournal.TYPE_SALE,
                "sequence_prefix": "VTE",
            },
        )
        client_compte, _ = AccAccount.objects.get_or_create(
            tenant=tenant,
            code="411000",
            defaults={"name": "Clients", "account_class": "4", "type": "receivable"},
        )
        produit, _ = AccAccount.objects.get_or_create(
            tenant=tenant,
            code="701000",
            defaults={"name": "Ventes", "account_class": "7", "type": "income"},
        )
        return create_invoice(
            tenant=tenant,
            journal=journal,
            period=periode,
            date=dt.date(2026, 1, 15),
            partner_id=uuid.uuid4(),
            receivable_account=client_compte,
            income_lines=[{"account": produit, "amount": Decimal("100000"), "label": "Prestation"}],
        )


#: (nom lisible, constructeur, gabarit d'URL, champ d'état surveillé)
DOCUMENTS: list[tuple[str, Callable[[Tenant, User], Any], str, str]] = [
    ("commande de vente", _commande, "/sales/orders/{}/", "state"),
    ("opportunité", _opportunite, "/crm/{}/", "stage_id"),
    ("expédition", _expedition, "/logistics/shipments/{}/", "state"),
    ("facture", _facture, "/accounting/{}/", "invoice_state"),
]


@pytest.mark.parametrize(
    "libelle,constructeur,gabarit_url,champ_etat",
    DOCUMENTS,
    ids=[d[0] for d in DOCUMENTS],
)
def test_every_offered_step_does_something_or_says_why(
    libelle: str, constructeur: Callable[[Tenant, User], Any], gabarit_url: str, champ_etat: str
) -> None:
    """Parcourt le document d'un bout à l'autre de son cycle.

    **Tester seulement l'état initial ne suffit pas**, et c'est mesuré : les
    transitions dangereuses d'une facture — « Marquer réglée » sans écriture
    comptable — ne sont proposées qu'une fois la facture VALIDÉE. Un test
    qui n'ouvrirait que des brouillons ne les verrait jamais.

    À chaque état atteint, le test essaie CHAQUE étape proposée, chacune sur
    un exemplaire neuf obtenu en rejouant le chemin parcouru ; puis il avance
    d'un cran par la première étape et recommence."""
    tenant, user = _societe_et_utilisateur(
        f"DA{abs(hash(libelle)) % 900 + 99}", f"da-{abs(hash(libelle)) % 9999}@example.com"
    )
    client = _client(tenant, user)

    def _rejouer(chemin: list[dict[str, str]]) -> Any:
        objet = constructeur(tenant, user)
        for champs in chemin:
            client.post(gabarit_url.format(objet.id), champs)
        objet.refresh_from_db()
        return objet

    chemin_parcouru: list[dict[str, str]] = []
    etapes_essayees = 0
    etats_visites: set[str] = set()

    for profondeur in range(8):  # borne de sûreté : un cycle métier n'est pas infini
        depart = _rejouer(chemin_parcouru)
        etats_visites.add(str(getattr(depart, champ_etat)))
        with use_tenant(tenant.id):
            etapes = next_steps_for(depart, user)
        if profondeur == 0:
            assert etapes, (
                f"Aucune étape proposée sur une {libelle} neuve : le test ne mesure rien. "
                "Le jeu d'essai ou le résolveur a changé."
            )
        if not etapes:
            break

        avancee: dict[str, str] | None = None
        for etape in etapes:
            objet = _rejouer(chemin_parcouru)
            avant = getattr(objet, champ_etat)
            reponse = client.post(gabarit_url.format(objet.id), etape.champs())
            etapes_essayees += 1

            if reponse.status_code == 200:
                contenu = reponse.content.decode()
                assert "error" in contenu or "alert" in contenu or "erreur" in contenu.lower(), (
                    f"[{libelle}] l'étape « {etape.label} » a rendu la page sans rien changer "
                    f"et sans message : POST {etape.champs()}."
                )
                continue

            assert reponse.status_code == 302, (
                f"[{libelle}] l'étape « {etape.label} » rend {reponse.status_code} : "
                f"POST {etape.champs()}. Un bandeau ne doit jamais proposer ce que la garde "
                f"refuse — c'est la règle de C-1d."
            )
            objet.refresh_from_db()
            assert getattr(objet, champ_etat) != avant, (
                f"[{libelle}] l'étape « {etape.label} » a redirigé SANS RIEN CHANGER et sans "
                f"message : c'est le no-op silencieux que ce test interdit. Ce que le bandeau "
                f"poste — {etape.champs()} — n'est pas ce que la vue sait traiter."
            )
            if avancee is None:
                avancee = dict(etape.champs())

        # **On n'avance QUE par une étape qui a réellement abouti.** La
        # première version empilait la première étape proposée même quand
        # elle venait d'échouer pour une raison métier : le parcours
        # piétinait sur le même état, et la falsification F106 — qui casse
        # le vocabulaire des étapes de LIVRAISON — ne mordait pas, faute
        # d'atteindre ces états-là. Un parcours qui n'avance pas ne mesure
        # que son point de départ.
        if avancee is None:
            break
        chemin_parcouru.append(avancee)

    # **Le parcours doit AVANCER, sinon il ne mesure que son point de
    # départ.** Un seuil sur le nombre d'étapes essayées serait arbitraire —
    # une facture n'en propose qu'une, et c'est juste : son règlement passe
    # par un formulaire, pas par un bouton. Ce qui doit être vrai pour tout
    # document, c'est qu'au moins un état a succédé à un autre.
    assert len(etats_visites) >= 2, (
        f"[{libelle}] le parcours n'a jamais quitté l'état « {etats_visites} » : les "
        f"transitions proposées plus loin dans le cycle ne sont pas mesurées "
        f"({etapes_essayees} étape(s) essayée(s))."
    )


def test_a_step_whose_own_right_is_missing_is_not_offered_at_all() -> None:
    """Le bandeau ne propose pas ce que la garde refusera.

    Mesuré : l'écran des factures exige `accounting.validate_accmove` pour
    valider (`apps/accounting/views.py:94-98`), alors que le socle ne
    vérifiait que `change_accmove`. Un rôle doté de `change` sans `validate`
    — ce que `grant_module_access` produit exactement — se voyait proposer
    « Valider la facture » et recevait 403 au clic. C'est la règle de C-1d,
    refaite par le socle : une action sans droit DISPARAÎT, elle n'est pas
    grisée."""
    tenant = Tenant.objects.create(code="DAP", name="Societe droits")
    user = User.objects.create_user(email="da-partiel@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "accounting")  # view/add/change, jamais validate
    assert user.has_perm("accounting.change_accmove"), "Le jeu d'essai ne donne plus l'écriture."
    assert not user.has_perm("accounting.validate_accmove"), (
        "Le jeu d'essai donne désormais le droit de valider : il ne mesure plus rien."
    )

    facture = _facture(tenant, user)
    with use_tenant(tenant.id):
        etapes = next_steps_for(facture, user)

    libelles = [etape.label for etape in etapes]
    assert not any("Valider" in libelle for libelle in libelles), (
        f"Le bandeau propose une validation que la garde refusera en 403 : {libelles}."
    )


def test_the_leading_step_is_the_business_next_step_not_the_escape_hatch() -> None:
    """Le premier bouton du bandeau est celui que l'exploitant doit prendre.

    Mesuré avant correction : `get_available_user_state_transitions` rendait
    les transitions dans l'ordre de la machine à états — `cancel`,
    `confirm`, `send` — si bien que le bouton PRINCIPAL d'une commande
    neuve, rendu en premier et en `btn-primary`, était **« Annuler »**. Le
    commanditaire demande que l'utilisateur ait facilement idée de la suite
    à prendre ; lui proposer d'abord d'abandonner est l'exact contraire.

    L'ordre métier n'est connu que du module : il l'exprime par l'ordre de
    son dictionnaire de libellés, et le socle le respecte."""
    tenant, user = _societe_et_utilisateur("DAO", "da-ordre@example.com")
    commande = _commande(tenant, user)

    with use_tenant(tenant.id):
        etapes = next_steps_for(commande, user)

    assert etapes, "Aucune étape proposée sur une commande neuve."
    assert etapes[0].code == "send", (
        f"La suite mise en avant sur une commande en brouillon est « {etapes[0].label} » "
        f"(ordre reçu : {[e.code for e in etapes]}). L'ordre de la machine à états n'est pas "
        "l'ordre métier."
    )
