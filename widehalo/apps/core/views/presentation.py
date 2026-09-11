"""C-4 — choisir entre liste et kanban, et rendre le kanban.

**La presentation par defaut se DERIVE du processus**, comme le
commanditaire l'a demande : un document qui declare une projection
(`core.services.presentation`) s'ouvre en kanban ; un referentiel qui n'en
declare aucune s'ouvre en liste. L'utilisateur peut basculer, et sa
bascule — et elle seule — est enregistree (`ScreenPreference`). Le defaut,
lui, n'est jamais ecrit en base : sans cela il faudrait une ligne par
utilisateur et par ecran pour memoriser ce qui se recalcule.

**Le kanban ne pagine pas, il PLAFONNE — et il le dit.** Un tableau est
fait pour etre vu d'un coup ; le paginer n'a pas de sens. Mais une colonne
de dix mille cartes n'est pas rendable, d'ou un plafond par colonne. La
lecon de C-2 s'applique telle quelle : l'ecran de saisie rapide affichait
« les 50 ecritures les plus recentes » sans le dire, et au-dela les
ecritures disparaissaient. Chaque colonne annonce donc son total et le
nombre reellement montre.
"""

from __future__ import annotations

from typing import Any, cast

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.models.ui import ScreenPreference
from apps.core.models.user import User
from apps.core.services.presentation import COLONNES, Board, board_for
from apps.core.views.smart_table import EXPORT_FORMATS, Column, apply_search, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

PRESENTATION_LISTE = ScreenPreference.PRESENTATION_LISTE
PRESENTATION_KANBAN = ScreenPreference.PRESENTATION_KANBAN

#: Plafond de cartes par colonne. Annonce a l'ecran, jamais silencieux.
CARTES_PAR_COLONNE = 50


def _presentation_par_defaut(model_label: str) -> str:
    """Derivee du processus : un tableau declare, donc un kanban."""
    return PRESENTATION_KANBAN if board_for(model_label) is not None else PRESENTATION_LISTE


def _presentation_choisie(request: HttpRequest, *, table_key: str, model_label: str) -> str:
    """La presentation a rendre, et l'enregistrement de la bascule.

    Ordre : ce que l'utilisateur demande MAINTENANT, sinon ce qu'il a
    choisi la derniere fois, sinon ce que le processus dicte."""
    if board_for(model_label) is None:
        # Sans projection, il n'y a pas de kanban possible : inutile
        # d'enregistrer une preference que l'ecran ne saurait pas honorer.
        return PRESENTATION_LISTE

    # `request.user` est type `User | AnonymousUser` par defaut ; ces ecrans
    # sont tous derriere `@login_required` (C-1), d'ou le cast — meme geste
    # que `smart_table_response` pour `visible_saved_views`.
    utilisateur = cast(User, request.user)
    demande = request.GET.get("presentation")
    if demande in (PRESENTATION_LISTE, PRESENTATION_KANBAN):
        # `tenant` est obligatoire : `ScreenPreference` est un `BaseModel`,
        # donc sa table est en `FORCE ROW LEVEL SECURITY` et PostgreSQL
        # REFUSE une insertion sans societe. Mesure faite, pas supposee :
        # l'omettre leve « new row violates row-level security policy ».
        ScreenPreference.objects.update_or_create(
            tenant=resolve_tenant(request),
            owner=utilisateur,
            table_key=table_key,
            defaults={"presentation": demande},
        )
        return demande

    memorisee = (
        ScreenPreference.objects.filter(owner=utilisateur, table_key=table_key)
        .values_list("presentation", flat=True)
        .first()
    )
    return memorisee or _presentation_par_defaut(model_label)


def _colonnes_du_tableau(queryset: QuerySet[Any], board: Board) -> list[dict[str, Any]]:
    """Les cinq colonnes, chacune bornee EN BASE.

    **Le cahier l.505 : « aucune liste ne charge integralement son jeu de
    donnees, y compris a l'export ».** La premiere version de ce lot faisait
    exactement l'inverse : `for objet in queryset` chargeait les dix mille
    factures d'une societe pour n'en montrer cinquante par colonne. Le
    defaut est de ce lot-ci, et il enfreignait un critere ecrit.

    La projection declaree donne l'inverse dont on a besoin : de quels
    etats une colonne est faite. Deux requetes bornees par colonne non vide
    — un comptage et une tranche — remplacent le chargement complet, et le
    nombre de requetes ne depend plus du nombre de documents."""
    etats_par_colonne: dict[str, list[str]] = {code: [] for code, _libelle in COLONNES}
    for etat, colonne in board.par_etat.items():
        if colonne in etats_par_colonne:
            etats_par_colonne[colonne].append(etat)

    colonnes: list[dict[str, Any]] = []
    for code, libelle in COLONNES:
        etats = etats_par_colonne[code]
        if not etats:
            # Aucun etat n'alimente cette colonne : inutile d'interroger la
            # base pour apprendre qu'elle est vide.
            colonnes.append(
                {"code": code, "libelle": libelle, "cartes": [], "total": 0, "tronquee": False}
            )
            continue
        sous_ensemble = queryset.filter(**{f"{board.state_field}__in": etats})
        total = sous_ensemble.count()
        colonnes.append(
            {
                "code": code,
                "libelle": libelle,
                "cartes": list(sous_ensemble[:CARTES_PAR_COLONNE]),
                "total": total,
                "tronquee": total > CARTES_PAR_COLONNE,
            }
        )
    return colonnes


def presentation_response(
    request: HttpRequest,
    *,
    table_key: str,
    columns: list[Column],
    queryset: QuerySet[Any],
    page_template: str,
    model_label: str,
    page_context: dict[str, Any] | None = None,
    row_url_name: str = "",
) -> HttpResponse:
    """Rend l'ecran dans sa presentation courante.

    En LISTE, delegue entierement a `smart_table_response` : recherche,
    tri, pagination, colonnes masquables et export restent exactement ce
    qu'ils sont, ce lot n'y touche pas."""
    contexte = dict(page_context or {})
    presentation = _presentation_choisie(request, table_key=table_key, model_label=model_label)
    contexte["presentation"] = presentation
    contexte["kanban_disponible"] = board_for(model_label) is not None

    # **L'export part TOUJOURS par le composant, quelle que soit la
    # presentation.** Exporter porte sur les donnees, pas sur la facon de
    # les disposer : un lien d'export qui rendrait la page kanban au lieu
    # d'un fichier serait du decor, et c'est exactement ce que la garde de
    # C-2 verifie en DEMANDANT le fichier plutot qu'en constatant le lien.
    if request.GET.get("export") in EXPORT_FORMATS or presentation == PRESENTATION_LISTE:
        if row_url_name:
            contexte.setdefault("row_url_name", row_url_name)
        return smart_table_response(
            request,
            table_key=table_key,
            columns=columns,
            queryset=queryset,
            page_template=page_template,
            page_context=contexte,
        )

    # Le kanban filtre sur la MEME recherche que la liste. Sans cela, taper
    # dans le champ de recherche d'un tableau ne ferait rien — un controle
    # rendu et inerte.
    requete = request.GET.get("q", "")
    contexte["query"] = requete
    # `_presentation_choisie` rend la LISTE des qu'aucun tableau n'est
    # declare : atteindre cette branche implique donc qu'il y en a un. Le
    # `assert` dit cet invariant a mypy — meme geste qu'a
    # `apps/core/views/backup_admin.py:82`.
    tableau = board_for(model_label)
    assert tableau is not None
    contexte["colonnes_kanban"] = _colonnes_du_tableau(
        apply_search(queryset, columns, requete), tableau
    )
    contexte["row_url_name"] = row_url_name
    contexte["table_key"] = table_key
    return render(request, page_template, contexte)


def is_write_allowed(user: User, codename: str) -> bool:
    """Le kanban ne propose un deplacement qu'a qui peut ecrire — meme
    regle qu'en C-1d et C-4 (1/2)."""
    return bool(user.has_perm(codename))
