"""CRM-SCORE1 : scoring deterministe par regles (montant, etape/probabilite,
anciennete, historique d'activites) — pas de machine learning, un score
0-100 explicable et reproductible. CRM-WA1 : lien `wa.me` pre-rempli, pas
d'integration bidirectionnelle ici (differe, cf. canal WhatsApp du socle
Lot 1 pour les notifications applicatives, distinct de ce lien de contact
direct commercial->prospect)."""

from __future__ import annotations

import re
from urllib.parse import quote

from django.utils import timezone

from apps.crm.models import CrmLead

# Poids fixes, documentes explicitement pour rester explicables (RG-CRM :
# le cahier des charges demande un scoring deterministe, pas une boite noire).
AMOUNT_MAX_POINTS = 40
AMOUNT_REFERENCE_MGA = 10_000_000  # montant au-dela duquel le score-montant plafonne
STAGE_MAX_POINTS = 30
RECENCY_MAX_POINTS = 15
RECENCY_HALF_LIFE_DAYS = 14  # score de recence divise par 2 tous les 14 jours
ACTIVITY_MAX_POINTS = 15
ACTIVITY_POINTS_PER_ITEM = 3


def compute_lead_score(lead: CrmLead) -> int:
    amount_score = min(
        AMOUNT_MAX_POINTS,
        int(lead.expected_revenue_mga / AMOUNT_REFERENCE_MGA * AMOUNT_MAX_POINTS),
    )
    stage_score = int(lead.probability / 100 * STAGE_MAX_POINTS)

    age_days = (timezone.now() - lead.created_at).days
    recency_score = int(RECENCY_MAX_POINTS / (1 + age_days / RECENCY_HALF_LIFE_DAYS))

    activity_count = lead.activities.count()
    activity_score = min(ACTIVITY_MAX_POINTS, activity_count * ACTIVITY_POINTS_PER_ITEM)

    return min(100, amount_score + stage_score + recency_score + activity_score)


def whatsapp_contact_link(lead: CrmLead, *, message: str | None = None) -> str | None:
    """Retourne None si l'opportunite n'a pas de numero de telephone —
    jamais de lien casse a defaut de donnee."""
    if not lead.phone:
        return None

    digits = re.sub(r"[^0-9]", "", lead.phone)
    if not digits:
        return None

    text = message or f"Bonjour {lead.contact_name or ''}, au sujet de {lead.name}".strip()
    return f"https://wa.me/{digits}?text={quote(text)}"
