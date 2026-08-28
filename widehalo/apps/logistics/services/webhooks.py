"""LOG6 : signature HMAC des webhooks transporteurs (API-6). Aucun
mecanisme de signature HMAC generalise n'existait ailleurs dans ce depot
avant ce lot — le webhook WhatsApp entrant (Lot 1) utilise le mecanisme de
verification propre a l'API Meta Cloud, pas un HMAC generique
reutilisable. Construit ici, dans `logistics`, pas dans `core` : aucun
autre module n'a encore eu besoin d'un webhook signe generique — a
generaliser vers `core` si un futur module en a besoin a son tour."""

from __future__ import annotations

import hashlib
import hmac

from apps.logistics.models import LogServiceProvider


def verify_carrier_webhook_signature(
    provider: LogServiceProvider, *, payload: bytes, signature: str
) -> bool:
    """Verifie une signature HMAC-SHA256 hexadecimale (`X-Signature` ou
    equivalent selon le transporteur — le nom d'en-tete HTTP reste a la
    charge de la vue appelante, cette fonction ne fait que la
    verification cryptographique). Renvoie toujours `False` (jamais une
    exception) si le prestataire n'a pas de `webhook_secret` configure —
    un webhook non configure pour la signature ne doit jamais etre traite
    comme valide par defaut."""
    if not provider.webhook_secret:
        return False
    expected = hmac.new(
        provider.webhook_secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
