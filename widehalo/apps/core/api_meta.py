from django.conf import settings
from ninja import Router, Schema

from apps.core.idempotency import idempotent

router = Router(tags=["meta"])


@router.get("/meta", auth=None)
def meta(request):
    return {
        "api_version": "v1",
        "languages": [code for code, _label in settings.LANGUAGES],
        "default_language": settings.LANGUAGE_CODE,
        "base_currency": "MGA",
    }


class EchoIn(Schema):
    message: str


@router.post("/meta/echo")
@idempotent
def echo(request, payload: EchoIn):
    """Point de demonstration du mecanisme d'idempotence transversal — le
    meme motif (@idempotent + Idempotency-Key) sera reutilise tel quel par
    les futurs endpoints comptables/stock qui en ont besoin."""
    return {"message": payload.message}
