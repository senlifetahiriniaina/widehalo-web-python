"""SAL-NOTIF1 (§5.5.9, S7) : "lien WhatsApp manuel" — un commercial genere
un lien `wa.me` pre-rempli qu'il envoie lui-meme au client (aucun envoi
automatique, coherent avec la portee documentee sur
`apps.sales.services.orders._notify_salesperson`). Meme patron que
`apps.crm.services.scoring.whatsapp_contact_link` (CRM-WA1) — reutilise sa
logique de normalisation/encodage plutot que d'en re-inventer une, mais
n'importe pas directement depuis `crm` (regle de couplage n1 : `sales` ne
peut importer que `apps.crm.services.public`, qui n'expose pas cette
fonction — c'est un helper de presentation, pas une donnee metier CRM a
exposer publiquement).

Note de perimetre, REVISEE le 13/09 (H-2) : la premiere version de ce
fichier constatait qu'aucun tiers ne portait de numero de telephone, et
la fonction est restee SANS APPELANT depuis S7 pour cette raison.
`PartnerContact.phone` existe desormais, et `partners.services.public.
get_partner_phone` l'expose (contact principal, a defaut le premier qui
en porte un). La fonction prend toujours le numero en parametre : c'est
l'appelant (`sales.views.quotation_detail`) qui le resout, jamais ce
module, qui ne fait que composer un lien.
"""

from __future__ import annotations

import re
from urllib.parse import quote


def build_whatsapp_link(phone: str, message: str) -> str | None:
    """Retourne `None` si aucun chiffre exploitable n'est trouve dans
    `phone` — jamais un lien casse (meme discipline que
    `crm.services.scoring.whatsapp_contact_link`)."""
    digits = re.sub(r"[^0-9]", "", phone or "")
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"
