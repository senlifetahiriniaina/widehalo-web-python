"""Conventions d'erreur transversales : tout endpoint django-ninja renvoie
ses erreurs au format RFC 7807 (`application/problem+json`)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
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
