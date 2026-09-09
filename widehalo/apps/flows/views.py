"""T8 (bloc H, CON-1) — le journal des echanges, et le chemin retour vers la
piece.

**Le critere, dans sa seconde moitie** : « Depuis toute piece metier, l'etat
de ses echanges est atteignable en un clic, **et reciproquement depuis toute
ligne du journal**. »

**Ce qui n'existait pas.** `apps/flows` n'avait ni `views.py` ni `urls.py`
avant ce lot : il n'y avait aucun ecran de journal, donc aucune ligne d'ou
cliquer. Le sens « piece -> echanges » etait tenu au quart (un fragment sur
la seule facture) ; le sens reciproque ne l'etait pas du tout.

**Le hub ne connait aucun module, et cet ecran non plus.** La colonne
« Piece » et son lien viennent de `FlwExchange.document_label` /
`smart_table_url`, qui lisent le registre `core.services.document_screens`
alimente par chaque module metier depuis son `apps.py::ready()`. Aucun
import de `accounting`, `sales` ou `partners` ici — `apps/flows/module.py`
ne declare que `core`, et c'est structurel.

**Qui y a acces, et pourquoi si peu.** `flows.view_flwexchange`, detenu par
`admin` et `direction` seuls (`core.services.rbac_policy`). Un echange dit
vers QUI une piece est partie, avec quelle empreinte et quel verdict : c'est
une donnee d'exploitation et de preuve, pas une donnee de travail
quotidien. Un commercial n'a aucune raison de lire le journal des
soumissions fiscales.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse

from apps.core.views.smart_table import Column, smart_table_response
from apps.flows.models import FlwExchange, FlwLink

JOURNAL_COLUMNS = [
    # La PIECE en premier : c'est la colonne que le data grid transforme en
    # lien, et c'est le geste que CON-1 demande. `search_key` pointe le
    # champ reel — chercher sur une propriete Python leverait une
    # `FieldError` des la premiere frappe (defaut deja paye sur la liste des
    # opportunites, cf. `Column.search_key`).
    Column(key="document_label", label="Pièce", search_key="document_type"),
    # Les trois colonnes suivantes affichent des LIBELLES et cherchent sur
    # les champs reels. Afficher `operation`/`state` bruts ferait lire
    # « push_document » et « accepte » a un comptable — §10.3 refuse de
    # remonter le vocabulaire technique tel quel.
    Column(key="connector_code", label="Destinataire", search_key="link__connector__code"),
    Column(key="operation_label", label="Opération", search_key="operation"),
    Column(key="state_label", label="État", search_key="state"),
    Column(key="attempt", label="Tentative", searchable=False),
    Column(key="created_at", label="Date", searchable=False),
]


def _parse_date(valeur: str | None) -> dt.date | None:
    """Une date de filtre mal saisie ne casse pas l'ecran.

    Un journal qui rendrait 500 sur `?since=hier` serait inutilisable
    precisement le jour ou on le consulte en urgence — et c'est la classe de
    defaut que le lot T4bis a fermee partout ailleurs."""
    if not valeur:
        return None
    try:
        return dt.date.fromisoformat(valeur)
    except ValueError:
        return None


@login_required
def exchange_journal(request: HttpRequest) -> HttpResponse:
    """Le journal filtrable du §10.2 : « recherche par piece, tiers, statut,
    periode ».

    Les quatre filtres sont des parametres d'URL, ce qui les rend
    PARTAGEABLES : le fragment pose sur une piece pointe ici avec
    `?document_id=...`, et c'est ce qui ferme la boucle de CON-1 dans les
    deux sens.

    Le controle de droit est ecrit ici et non par un decorateur :
    `core.services.permissions.require_permission` est concu pour un
    endpoint django-ninja (il rend une erreur d'API), et le poser sur une
    vue d'ecran rendrait une reponse JSON a un navigateur. Meme forme que
    `core.views.admin_users`, seul autre ecran du depot garde par une
    permission."""
    if not request.user.has_perm("flows.view_flwexchange"):
        return HttpResponse(status=403)

    queryset = FlwExchange.objects.select_related("link__connector")

    etat = request.GET.get("state") or ""
    if etat:
        queryset = queryset.filter(state=etat)

    connecteur = request.GET.get("connector") or ""
    if connecteur:
        queryset = queryset.filter(link__connector__code=connecteur)

    document_id = request.GET.get("document_id") or ""
    if document_id:
        # Filtre venu du fragment pose sur une piece. Non type volontairement
        # a la lecture : un identifiant malforme doit rendre une liste vide,
        # jamais un 500 (garde `test_identifiers_are_typed`).
        if _est_uuid(document_id):
            queryset = queryset.filter(document_id=document_id)
        else:
            queryset = queryset.none()

    depuis = _parse_date(request.GET.get("since"))
    if depuis is not None:
        queryset = queryset.filter(created_at__date__gte=depuis)
    jusqu_a = _parse_date(request.GET.get("until"))
    if jusqu_a is not None:
        queryset = queryset.filter(created_at__date__lte=jusqu_a)

    return smart_table_response(
        request,
        table_key="flows.exchange_journal",
        columns=JOURNAL_COLUMNS,
        queryset=queryset,
        page_template="flows/exchange_journal.html",
        page_context={
            "state_filter": etat,
            "states": FlwExchange.STATE_CHOICES,
            "connector_filter": connecteur,
            "connectors": _connector_codes(),
            "since": request.GET.get("since") or "",
            "until": request.GET.get("until") or "",
            "document_id": document_id,
        },
    )


def _est_uuid(valeur: str) -> bool:
    from uuid import UUID

    try:
        UUID(valeur)
    except ValueError:
        return False
    return True


def _connector_codes() -> list[str]:
    """Les connecteurs de CETTE societe, pour que le filtre soit une liste
    et non une saisie libre.

    Lu depuis les LIAISONS et non depuis le catalogue : deux societes d'une
    meme instance n'ont pas les memes raccordements, et proposer un
    connecteur qu'on n'a pas revient a proposer un filtre qui ne rendra
    jamais rien."""
    return sorted(FlwLink.objects.values_list("connector__code", flat=True).distinct())
