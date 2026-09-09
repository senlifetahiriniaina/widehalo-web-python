"""T5 (bloc D, PAY-1) — l'interface unique d'encaissement, et ses deux voies.

**Le critère** : « Le basculement d'un tenant entre agrégateur et
raccordement direct s'effectue **par paramètre**, sans modification de code
et sans reprise des intentions en cours. »

Les deux dernières exigences décident de la forme :

- *sans modification de code* → le choix vit dans une donnée du tenant, et
  ce module ne connaît que des CODES, jamais des `if` par fournisseur ;
- *sans reprise des intentions en cours* → une intention déjà émise reste
  servie par la voie qui l'a émise. C'est pourquoi
  `AccPaymentIntent.provider_code` est écrit À LA CRÉATION et jamais relu
  depuis le tenant : basculer le paramètre ne doit pas orphelin les
  intentions parties la veille.

**Ce module ne fait aucun appel réseau, et ne peut pas en faire.** La règle
de couplage n°1 l'interdit à tout module métier, et une garde CI le
vérifie depuis S6. L'émission part par le hub (`OP_INITIATE_PAYMENT`), la
notification revient par lui. Ce fichier ne décrit donc que ce qu'une voie
EST — son code, son libellé, la façon dont elle nomme ses références — pas
comment on lui parle.

**Réserve sur les opérateurs malgaches.** Aucun export ni aucune
spécification d'API réelle de Mvola, Orange Money ou Airtel Money n'est
accessible à ce dépôt — `services/mobile_money.py` porte déjà cette
réserve pour son format CSV, et elle vaut ici. Les deux voies déclarées
ci-dessous décrivent une STRUCTURE (agrégateur qui verse en groupé,
raccordement direct qui verse à l'unité), pas un fournisseur nommé. Le
jour où un contrat réel existe, c'est une entrée de plus dans ce
registre — pas une reprise de code.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: Longueur minimale d'une réserve écrite — même seuil que les autres
#: registres à motif du dépôt.
RESERVE_MINIMUM = 40

#: L'agrégateur : un intermédiaire qui encaisse pour le compte du tenant et
#: reverse GROUPÉ, commission déduite. C'est ce versement groupé qui rend
#: le rapprochement de second niveau nécessaire (PAY-5), et le cahier le
#: désigne comme « la partie du bloc D que l'on sous-estime
#: systématiquement ».
PROVIDER_AGGREGATOR = "agregateur"
#: Le raccordement direct : le tenant est en relation avec l'opérateur, qui
#: verse à l'unité. Pas de versement groupé, donc pas de second niveau —
#: mais une commission qui peut être prélevée à la source, donc un montant
#: reçu inférieur au montant dû.
PROVIDER_DIRECT = "raccordement_direct"

PROVIDER_CHOICES: list[tuple[str, str | Promise]] = [
    (PROVIDER_AGGREGATOR, _("Agrégateur (versement groupé)")),
    (PROVIDER_DIRECT, _("Raccordement direct (versement à l'unité)")),
]
KNOWN_PROVIDERS: frozenset[str] = frozenset(code for code, _label in PROVIDER_CHOICES)


@dataclass(frozen=True)
class PaymentProvider:
    """Ce qu'une voie d'encaissement EST, en données.

    `settles_in_batch` n'est pas un détail d'implémentation : c'est ce qui
    décide si un rapprochement de second niveau doit exister pour ce
    tenant. Le déduire d'un `if provider == "agregateur"` dispersé dans le
    code aurait rendu l'ajout d'une troisième voie impossible sans relire
    tout le module."""

    code: str
    label: str | Promise
    settles_in_batch: bool
    reserve: str

    def __post_init__(self) -> None:
        if self.code not in KNOWN_PROVIDERS:
            raise ValidationError(
                _("Voie d'encaissement hors du jeu fermé : %(code)s.") % {"code": self.code}
            )
        if len(self.reserve) < RESERVE_MINIMUM:
            raise ValidationError(
                _(
                    "La réserve de la voie « %(code)s » fait %(n)s caractères ; il en "
                    "faut au moins %(min)s. Une voie d'encaissement sans réserve "
                    "écrite se lit comme un raccordement éprouvé."
                )
                % {"code": self.code, "n": len(self.reserve), "min": RESERVE_MINIMUM}
            )


_RESERVE = (
    "structure retenue en l'absence de contrat réel : aucune spécification d'API "
    "Mvola, Orange Money ou Airtel Money n'est accessible à ce dépôt, et "
    "`services/mobile_money.py` porte déjà la même réserve pour son format de "
    "relevé. Ce qui est décrit ici est la FORME du règlement (groupé ou à "
    "l'unité), jamais un fournisseur nommé. À confirmer contrat en main avant "
    "tout raccordement en production."
)

PROVIDERS: dict[str, PaymentProvider] = {
    PROVIDER_AGGREGATOR: PaymentProvider(
        code=PROVIDER_AGGREGATOR,
        label=_("Agrégateur (versement groupé)"),
        settles_in_batch=True,
        reserve=_RESERVE,
    ),
    PROVIDER_DIRECT: PaymentProvider(
        code=PROVIDER_DIRECT,
        label=_("Raccordement direct (versement à l'unité)"),
        settles_in_batch=False,
        reserve=_RESERVE,
    ),
}


def get_provider(code: str) -> PaymentProvider | None:
    """La voie déclarée, ou `None`.

    `None` plutôt qu'un repli sur l'agrégateur : servir une intention par
    une voie que le tenant n'a pas choisie enverrait de l'argent par un
    chemin qu'il n'a pas décidé."""
    return PROVIDERS.get((code or "").strip())


def resolve_tenant_provider(tenant: object) -> PaymentProvider | None:
    """La voie CONFIGURÉE pour ce tenant, lue sur son paramétrage.

    Rend `None` quand rien n'est configuré — état normal de toute
    installation qui n'encaisse pas par mobile, et qui ne doit surtout pas
    se voir attribuer une voie par défaut."""
    code = getattr(tenant, "mobile_payment_provider", "") or ""
    return get_provider(code)


__all__ = [
    "KNOWN_PROVIDERS",
    "PROVIDERS",
    "PROVIDER_AGGREGATOR",
    "PROVIDER_CHOICES",
    "PROVIDER_DIRECT",
    "RESERVE_MINIMUM",
    "PaymentProvider",
    "get_provider",
    "resolve_tenant_provider",
]
