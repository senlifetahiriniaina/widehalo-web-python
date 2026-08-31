from __future__ import annotations

from typing import Any

from django import template
from django.urls import reverse

register = template.Library()


@register.filter(name="getattr")
def get_attribute(obj: Any, key: str) -> Any:
    """Acces dynamique a un attribut par nom de champ (utilise par le
    composant SmartTable, dont les colonnes sont declarees comme de simples
    chaines cote vue)."""
    return getattr(obj, key, "")


@register.filter(name="dict_get")
def dict_get(mapping: Any, key: str) -> Any:
    """Acces par cle a un dict depuis un template (ex. mesures gradees par
    taille, `patronage/detail.html`) — les templates Django ne permettent
    pas `mapping[key]` avec une variable de boucle directement."""
    if not isinstance(mapping, dict):
        return ""
    return mapping.get(key, "")


@register.filter(name="reverse_with_pk")
def reverse_with_pk(row: Any, url_name: str) -> str:
    """Resout l'URL de detail d'une ligne SmartTable (`row_url_name` passe
    en `page_context`), sans coupler le composant a un module particulier."""
    if not url_name:
        return ""
    return reverse(url_name, args=[row.id])


_BADGE_SUCCESS_TOKENS = (
    "paid",
    "payee",
    "paye",
    "validated",
    "valide",
    "confirmed",
    "confirme",
    "resolved",
    "resolue",
    "resolu",
    "active",
    "actif",
    "done",
    "termine",
    "closed",
    "cloture",
    "delivered",
    "livre",
    "won",
    "gagne",
    "achieved",
    "on_track",
    "posted",
    "approved",
    "approuve",
)
_BADGE_WARNING_TOKENS = (
    "sent",
    "envoye",
    "pending",
    "attente",
    "in_progress",
    "in_transit",
    "en_cours",
    "to_validate",
    "a_valider",
    "draft",
    "brouillon",
    "partially",
    "partiel",
    "at_risk",
    "suggested",
    "submitted",
    "escalated",
)
_BADGE_DANGER_TOKENS = (
    "cancelled",
    "canceled",
    "annule",
    "failed",
    "echoue",
    "echec",
    "rejected",
    "refuse",
    "blocked",
    "bloque",
    "overdue",
    "en_retard",
    "lost",
    "perdu",
    "missed",
    "off_track",
    "dispute",
    "litige",
    "unresolvable",
    "expired",
    "expire",
    "revoked",
    "revoque",
)


@register.filter(name="state_badge_class")
def state_badge_class(value: Any) -> str:
    """Heuristique de correspondance de sous-chaines entre une valeur d'etat
    (state/status brut ou libelle affiche) et une variante de couleur de
    `.badge` (cf. static/css/app.css) — pas de table de correspondance par
    module, un simple filtre reutilisable sur tout ecran (chantier UX5)."""
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        return "b-neutral"
    for token in _BADGE_DANGER_TOKENS:
        if token in normalized:
            return "b-fail"
    for token in _BADGE_SUCCESS_TOKENS:
        if token in normalized:
            return "b-success"
    for token in _BADGE_WARNING_TOKENS:
        if token in normalized:
            return "b-pending"
    return "b-neutral"
