"""Conventions d'erreur transversales : tout endpoint django-ninja renvoie
ses erreurs au format RFC 7807 (`application/problem+json`)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import (
    ObjectDoesNotExist,
    PermissionDenied,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.errors import ValidationError as NinjaValidationError


class ProblemDetailResponse(JsonResponse):
    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: str = "",
        type_: str = "about:blank",
        instance: str = "",
        **extra: Any,
    ) -> None:
        body = {
            "type": type_,
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
            **extra,
        }
        super().__init__(body, status=status, content_type="application/problem+json")


def register_exception_handlers(api: NinjaAPI) -> None:
    @api.exception_handler(NinjaValidationError)
    def on_validation_error(request: Any, exc: NinjaValidationError) -> JsonResponse:
        return ProblemDetailResponse(
            status=422,
            title="Erreur de validation",
            detail="Un ou plusieurs champs sont invalides.",
            instance=request.path,
            errors=exc.errors,
        )

    @api.exception_handler(PermissionDenied)
    def on_permission_denied(request: Any, exc: PermissionDenied) -> JsonResponse:
        # Convertit toute PermissionDenied levee par un service metier (ex.
        # approvals.decide) en 403 — sans ce handler, elle tombait dans le
        # handler generique Exception ci-dessous (500 en production).
        return ProblemDetailResponse(
            status=403,
            title="Permission refusée",
            detail=str(exc) or "permission refusée",
            instance=request.path,
        )

    @api.exception_handler(DjangoValidationError)
    def on_domain_validation_error(request: Any, exc: DjangoValidationError) -> JsonResponse:
        """Une `ValidationError` de Django est une ENTREE INVALIDE, pas une
        panne du serveur — 422, jamais 500.

        **Ce que ce gestionnaire repare, mesure a l'appui.** La campagne de
        contrat (`tests/contract/test_openapi_schemathesis.py`) mesure 264
        des 590 operations rendant un 500 sur entree malformee. La cause
        est unique et tient en une phrase : un identifiant UUID malforme
        recu dans un parametre declare `str` traverse la validation de
        schema, puis fait lever `Model.objects.get(id=...)` d'une
        `ValidationError` que PERSONNE ne rattrapait — elle tombait donc
        dans le gestionnaire generique ci-dessous.

        Le gestionnaire de `PermissionDenied` a ete ajoute un jour pour
        exactement la meme raison, et son commentaire le dit. C'est la meme
        classe de defaut, une exception plus loin.

        **Et le defaut deborde largement des entrees malformees.** Toute la
        couche service de ce depot leve `ValidationError` pour refuser une
        operation metier — une transition d'echange interdite, une
        correspondance incomplete, une operation hors du jeu ferme. Chacun
        de ces refus, parfaitement volontaire et parfaitement documente,
        rendait un 500 des lors qu'il traversait un endpoint : un refus
        legitime presente a l'utilisateur comme une panne du produit.

        Le message est REPERCUTE, contrairement au 500 generique : c'est
        toute la difference entre « une erreur inattendue est survenue » et
        « le connecteur ne declare pas l'operation OP3 ». Les messages de
        service sont ecrits pour etre lus — c'est leur objet — et ils sont
        rediges des secrets a la source (FLX-8) partout ou ils recopient un
        tiers."""
        return ProblemDetailResponse(
            status=422,
            title="Entrée invalide",
            detail="; ".join(exc.messages) if exc.messages else "entrée invalide",
            instance=request.path,
        )

    @api.exception_handler(ObjectDoesNotExist)
    def on_object_does_not_exist(request: Any, exc: ObjectDoesNotExist) -> JsonResponse:
        """Un objet demande qui n'existe pas est un 404, jamais un 500.

        `Model.DoesNotExist` herite d'`ObjectDoesNotExist` : ce
        gestionnaire couvre donc tout `.objects.get()` d'un endpoint qui ne
        trouve rien — y compris, et c'est le cas le plus frequent sur une
        instance multi-societes, un identifiant parfaitement valide mais
        appartenant a une AUTRE societe, que `TenantManager` rend
        invisible. Rendre 500 dans ce cas transformerait une isolation qui
        fonctionne en incident de production.

        **Le detail ne dit pas ce qui n'a pas ete trouve**, et c'est
        deliberé : distinguer « cet objet n'existe pas » de « cet objet ne
        vous est pas accessible » revient a confirmer son existence a qui
        n'y a pas droit. Meme posture que le rejet de webhook de §8.2,
        « sans reveler pourquoi »."""
        return ProblemDetailResponse(
            status=404,
            title="Introuvable",
            detail="La ressource demandée n'existe pas ou n'est pas accessible.",
            instance=request.path,
        )

    @api.exception_handler(Exception)
    def on_unhandled_exception(request: Any, exc: Exception) -> JsonResponse:
        if settings.DEBUG:
            raise exc
        return ProblemDetailResponse(
            status=500,
            title="Erreur interne",
            detail="Une erreur inattendue est survenue.",
            instance=request.path,
        )
