"""L'imputation du cout d'un message, et l'unite sous laquelle elle se fait.

**Ce module existe parce que « le compteur est deja au message » etait vrai
et insuffisant.** Le cout etait impute ligne par ligne, ce qui est correct
sous facturation AU MESSAGE et faux sous facturation A LA CONVERSATION —
ou une fenetre de 24 h par categorie est facturee UNE fois quel que soit le
nombre de messages qu'elle porte. Le compteur sur-comptait donc si le
regime en vigueur etait celui de la conversation, et rien ne permettait de
savoir lequel s'appliquait.

**Le total reste une somme, dans les deux cas.** C'est la regle
d'IMPUTATION qui change, pas la regle d'agregation : sous facturation a la
conversation, l'ouverture de la fenetre porte le prix et les messages
suivants portent zero. Cela vaut mieux qu'un agregat qui regrouperait a la
lecture — un regroupement a la lecture donnerait un total different selon
la fenetre interrogee, et un plafond mensuel ne saurait plus ce qu'il
compte.

**`conversation_id` trouve ici son premier lecteur.** Le champ etait ecrit
par les trois ecrivains de `WhatsAppMessage` et lu par personne — le seul
lecteur du depot etait un test verifiant qu'il n'etait pas nul. C'est
exactement le motif que ce projet corrige depuis le debut : une donnee
correcte, correctement documentee, que rien n'interroge. Il devient la clef
de la fenetre de facturation.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.core.cost_units import COST_UNIT_MESSAGE, cost_unit_in_force
from apps.core.models.notification import WhatsAppMessage

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant
    from apps.whatsapp.models import WaMessageTemplate

#: La fenetre de facturation d'une conversation. Meme duree que la fenetre
#: de service (`WaConversation.SERVICE_WINDOW`), et ce n'est pas un hasard :
#: Meta fait coincider les deux. La constante est neanmoins ecrite ici
#: plutot qu'importee, parce que les deux notions sont distinctes — l'une
#: dit quand on a le DROIT de repondre, l'autre ce qu'on PAIE — et les lier
#: par un import ferait qu'un changement de l'une deplacerait l'autre sans
#: qu'on s'en apercoive.
BILLING_WINDOW = dt.timedelta(hours=24)


def window_already_billed(
    tenant: Tenant, *, conversation_id: UUID | None, category: str, now: dt.datetime | None = None
) -> bool:
    """Une fenetre de facturation est-elle deja ouverte et payee ?

    Cherche un message SORTANT de la meme conversation et de la meme
    categorie, facture dans les 24 dernieres heures. La categorie fait
    partie de la clef parce que Meta facture par categorie : une fenetre
    utilitaire et une fenetre marketing sur le meme numero sont deux
    conversations facturables distinctes.

    `cost_ariary__gt=0` et non `isnull=False` : une ligne a zero est
    justement celle qui a ete portee par une fenetre deja payee, ou une
    reponse gratuite. La compter comme ouvrant la fenetre rendrait la
    seconde fenetre gratuite elle aussi."""
    if conversation_id is None:
        # Sans conversation, aucune fenetre n'est identifiable : on facture,
        # ce qui est le choix prudent. Sous-facturer est un manque a gagner
        # invisible ; sur-facturer se voit sur la jauge et se corrige.
        return False
    moment = now or timezone.now()
    return WhatsAppMessage.objects.filter(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        conversation_id=conversation_id,
        category=category,
        created_at__gte=moment - BILLING_WINDOW,
        cost_ariary__gt=Decimal(0),
    ).exists()


def impute_cost(
    tenant: Tenant,
    *,
    template: WaMessageTemplate,
    conversation_id: UUID | None,
    now: dt.datetime | None = None,
    is_free_service_reply: bool = False,
) -> tuple[Decimal, str]:
    """Le couple (montant, unite) a inscrire sur la ligne.

    `is_free_service_reply` couvre la reponse envoyee DANS la fenetre de
    service, a l'initiative du client. Elle est gratuite sous les deux
    regimes de facturation — c'est une reponse, pas une sollicitation — et
    elle etait pourtant facturee plein tarif. Zero et non `None` : la
    difference compte, et elle est la meme que sur `FlwExchange.cost_ariary`
    — un envoi gratuit vaut zero, un envoi dont le tarif n'est pas encore
    connu vaut `None`."""
    moment = now or timezone.now()
    unit = cost_unit_in_force(at_date=moment.date(), tenant=tenant)

    if is_free_service_reply:
        return Decimal(0), unit
    if unit == COST_UNIT_MESSAGE:
        return template.estimated_cost_ariary, unit
    if window_already_billed(
        tenant, conversation_id=conversation_id, category=template.category, now=moment
    ):
        return Decimal(0), unit
    return template.estimated_cost_ariary, unit


__all__ = ["BILLING_WINDOW", "impute_cost", "window_already_billed"]
