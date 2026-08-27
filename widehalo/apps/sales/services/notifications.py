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

Note de perimetre (verifiee avant d'ecrire ce fichier) :
`apps.partners.models.Partner` n'a AUCUN champ telephone a ce jour (lu en
entier, aucun champ `phone`/`mobile`/`tel`) et
`apps.partners.services.public` n'expose donc rien de tel non plus — il
est impossible de resoudre un numero a partir d'un seul `partner_id` dans
ce lot. Plutot que d'ajouter un getter qui renverrait toujours `None`
(gap fictif), cette fonction prend directement un numero de telephone en
parametre : elle est appelable des qu'un ecran/appelant dispose du numero
par un autre moyen (ex. `SalesQuotation.contact`/`delivery_address`
saisis a la main, ou une future integration `partners`)."""

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
