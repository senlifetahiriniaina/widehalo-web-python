"""T9 (CON-2, §9.1) — ce qu'une liaison ferait sortir, et qui l'a accepte.

**Le critere** : « L'activation d'un connecteur exige un consentement
affichant categories de donnees, tiers, pays et duree de conservation
connue ; la decision est journalisee avec son auteur. »

**Les categories sont DERIVEES, jamais saisies.** Le §10.2 l'exige
nommement pour l'ecran de consentement : « le texte des categories est
genere depuis la declaration de l'adaptateur, jamais redige a la main —
sinon il devient faux a la premiere evolution ». Elles se lisent donc sur
les correspondances de la liaison : chaque correspondance designe un
document, chaque document declare sa categorie §9.2 dans le registre pose
au lot T0. Personne ne les tape.

**Une liaison sans correspondance ne fait rien sortir, et le dire est
utile.** C'est l'etat d'une liaison qu'on vient de creer : le consentement
serait vide, et un ecran qui afficherait « aucune categorie » plutot qu'une
liste rassurante dit la verite — il n'y a rien a consentir tant qu'aucune
correspondance n'existe.

**Ce module ne decide pas de l'activation** : il decrit et il enregistre.
C'est `services.public.activate_link` qui refuse, parce que c'est le seul
chemin d'activation du depot et qu'une garde posee ailleurs se contournerait
en appelant celui-la.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.core.services.outbound_schemas import CATEGORIES, get_outbound_document
from apps.flows.models import FlwConsent, FlwMapping

if TYPE_CHECKING:
    import datetime as dt

    from apps.core.models.user import User
    from apps.flows.models import FlwLink


def declared_categories(link: FlwLink) -> list[str]:
    """Les codes de categorie §9.2 que les correspondances ACTIVES de cette
    liaison feraient sortir, dedupliques et ordonnes.

    Ordonnes pour que deux lectures successives rendent la meme chose : un
    ecran de consentement dont les lignes changent de place a chaque
    rafraichissement ferait douter de ce qu'il affiche."""
    codes: set[str] = set()
    document_types = (
        FlwMapping.objects.filter(link=link, is_active=True)
        .values_list("document_type", flat=True)
        .distinct()
    )
    for document_type in document_types:
        document = get_outbound_document(document_type)
        if document is not None:
            codes.add(document.category)
    return sorted(codes)


def describe_consent(link: FlwLink) -> dict[str, Any]:
    """Les quatre informations du §9.1, telles que l'ecran doit les afficher
    AVANT validation.

    `retention_days` a `None` signifie « duree inconnue », et l'ecran doit
    le dire tel quel : le cahier ecrit « duree de conservation CONNUE »
    precisement parce qu'elle ne l'est pas toujours, et afficher un chiffre
    par defaut ferait affirmer au produit une duree que le tiers n'a jamais
    annoncee."""
    connector = link.connector
    codes = declared_categories(link)
    return {
        "categories": [
            {
                "code": code,
                "label": str(CATEGORIES[code].label),
                "rule": str(CATEGORIES[code].rule),
            }
            for code in codes
            if code in CATEGORIES
        ],
        "category_codes": codes,
        "third_party": connector.name or connector.code,
        "country_code": connector.country_code,
        "retention_days": connector.retention_days,
    }


def record_consent(
    link: FlwLink, *, granted_by: User, now: dt.datetime | None = None
) -> FlwConsent:
    """Enregistre la decision, en FIGEANT les quatre informations.

    Le gel n'est pas une commodite de stockage : ce qui a ete consenti ne
    doit pas changer sous les pieds de celui qui a consenti. Si une
    correspondance ajoutee demain fait sortir une categorie de plus, le
    consentement d'hier ne la couvre pas — et c'est l'ecart entre le gel et
    la derivation courante qui doit conduire a reconsentir."""
    description = describe_consent(link)
    return FlwConsent.objects.create(
        tenant=link.tenant,
        link=link,
        categories=description["category_codes"],
        third_party=description["third_party"],
        country_code=description["country_code"],
        retention_days=description["retention_days"],
        granted_by=granted_by,
        granted_at=now or timezone.now(),
    )


def current_consent(link: FlwLink) -> FlwConsent | None:
    """Le dernier consentement donne pour cette liaison, ou `None`."""
    return FlwConsent.objects.filter(link=link).order_by("-granted_at").first()


def consent_covers_current_scope(link: FlwLink) -> bool:
    """`True` si le consentement en vigueur couvre ce que la liaison ferait
    sortir AUJOURD'HUI.

    Faux quand une correspondance ajoutee depuis fait sortir une categorie
    que personne n'a acceptee — c'est exactement le cas que le gel rend
    visible, et il vaut mieux le nommer que le decouvrir au premier echange."""
    consent = current_consent(link)
    if consent is None:
        return False
    return set(declared_categories(link)) <= set(consent.categories or [])


__all__ = [
    "consent_covers_current_scope",
    "current_consent",
    "declared_categories",
    "describe_consent",
    "record_consent",
]
