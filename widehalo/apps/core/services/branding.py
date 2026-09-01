"""Marque d'entreprise (chantier "profil de l'entreprise + en-tete/pied de
page PDF") : encode `Tenant.logo` en data URI base64 pour affichage direct
via `<img src="...">`, meme idiome deja eprouve par
`apps.core.services.mfa.generate_totp_qr_data_uri` (QR code TOTP) — pas la
meme fonction (celle-ci lit un `ImageField` reellement stocke, pas une image
generee en memoire), mais le meme choix storage-agnostic : fonctionne
identiquement avec le stockage local actuel ou une future bascule S3,
contrairement a un chemin disque en dur transmis tel quel au gabarit PDF."""

from __future__ import annotations

import base64
import mimetypes

from apps.core.models.tenant import Tenant


def get_tenant_logo_data_uri(tenant: Tenant) -> str | None:
    """Retourne une data URI `data:<content-type>;base64,<...>` du logo du
    tenant, ou `None` si aucun logo n'est renseigne. Jamais d'exception :
    un tenant sans logo (cas normal, largement majoritaire tant que
    l'ecran "Profil de l'entreprise" n'a pas ete utilise) ne doit jamais
    casser le rendu d'un PDF qui consomme ce gap."""
    if not tenant.logo:
        return None
    content_type = mimetypes.guess_type(tenant.logo.name or "")[0] or "image/png"
    tenant.logo.open("rb")
    try:
        encoded = base64.b64encode(tenant.logo.read()).decode("ascii")
    finally:
        tenant.logo.close()
    return f"data:{content_type};base64,{encoded}"
