"""Veille prix fournisseurs Chine/Europe (PRC1-3, chantier « etudes de
faisabilite, veille prix fournisseurs, capacite 90j, risques
operationnels, qualite/certification, refonte UI/UX » — cf. plan,
sous-section « 2. Veille prix fournisseurs Chine/Europe »).

========================================================================
RESERVE DE SECURITE / LEGALITE — LIRE AVANT TOUTE MODIFICATION DE CE FICHIER
========================================================================
Decision deja actee et NON negociable (cf. plan) : un scraping HTTP reel
des plateformes commerciales visees (Alibaba, 1688, AliExpress, Europages,
Kompass...) se heurte tres souvent a des Conditions Generales d'Utilisation
qui l'interdisent explicitement, et les API officielles de ces plateformes
exigent des cles/contrats commerciaux que ce projet n'a pas. Consequence :

1. `StubPriceSourceProvider` est le provider actif PAR DEFAUT pour TOUTE
   plateforme, dans TOUS les environnements (dev/test/prod) — il ne fait
   RIGOUREUSEMENT AUCUN appel reseau (pas de `requests`, pas de socket, pas
   de bibliotheque HTTP importee). Il retourne un `PriceQuote` sans prix,
   avec `is_stub=True` et une note explicite invitant a configurer un
   connecteur reel.
2. `settings.PRICE_WATCH_PROVIDERS = {}` (dict vide) dans
   `config/settings/base.py` : AUCUNE plateforme n'est configuree par
   defaut. `get_provider_for_platform` ne bascule vers un connecteur reel
   QUE si l'utilisateur a explicitement rempli cette configuration avec
   des identifiants pour la plateforme concernee.
3. `GenericHttpPriceSourceProvider` ci-dessous est un SQUELETTE minimal
   d'implementation reelle (meme patron que `MetaCloudAPIClient` dans
   `apps.core.services.whatsapp` pour le canal WhatsApp Business, ou
   `InvoiceOCRProvider` dans `apps.accounting` — cf. leurs docstrings
   respectives pour le meme raisonnement applique ailleurs dans ce
   projet). Il N'EST JAMAIS INSTANCIE PAR DEFAUT. Son activation reste
   ENTIEREMENT SOUS LA RESPONSABILITE DE L'UTILISATEUR : avant de
   renseigner `settings.PRICE_WATCH_PROVIDERS` pour une plateforme donnee,
   verifier ses CGU/robots.txt et, si necessaire, souscrire son API
   officielle/un contrat commercial. Ce fichier ne fournit ni ne
   recommande aucun contournement de CGU (pas de rotation d'IP, pas de
   simulation de navigateur, pas de contournement de CAPTCHA) — un
   connecteur reel doit s'appuyer sur une source de donnees LICITE
   (API officielle, export contractuel, flux partenaire).
========================================================================

`run_price_watch_checks` orchestre la boucle complete (cible active et
echue -> provider -> nouveau `PrcPriceSnapshot` -> alerte d'ecart via
`apps.core.services.notifications.notify_role` — meme mecanisme
d'alerte que tout le reste du projet, jamais duplique)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.services.notifications import notify_role
from apps.purchase.models import PrcPriceSnapshot, PrcPriceWatchTarget

# Seuil d'ecart (valeur absolue, en pourcentage du dernier prix observe)
# au-dela duquel une alerte est envoyee au role `acheteur` (cf.
# `run_price_watch_checks`). Valeur choisie/documentee pour ce chantier :
# 15% — coherent avec l'ordre de grandeur deja retenu ailleurs dans ce
# projet pour un ecart "significatif" necessitant une revue humaine (ex.
# ecarts budgetaires analytiques `accounting`). A ajuster si un besoin
# metier plus precis est exprime plus tard (pas de configuration par
# plateforme/materiau a ce stade — simplification assumee).
PRICE_DEVIATION_ALERT_THRESHOLD_PCT = Decimal("15")

_FREQUENCY_TIMEDELTA: dict[str, dt.timedelta] = {
    PrcPriceWatchTarget.FREQUENCY_MONTHLY: dt.timedelta(days=30),
    PrcPriceWatchTarget.FREQUENCY_QUARTERLY: dt.timedelta(days=90),
}


@dataclass(frozen=True)
class PriceQuote:
    """Resultat d'une lecture de prix par un `PriceSourceProvider` —
    `price=None` signifie "aucun prix disponible" (cas systematique du
    stub, ou echec reseau d'un connecteur reel), jamais une exception :
    un provider ne doit jamais faire echouer `run_price_watch_checks`
    pour UNE cible a cause d'une autre."""

    price: Decimal | None
    currency: str
    is_stub: bool
    note: str = ""


class PriceSourceProvider(Protocol):
    """Interface d'un connecteur de veille prix — une implementation par
    plateforme (ou une implementation generique parametree). Ne DOIT
    jamais lever d'exception pour un echec de lecture "normal" (cible
    introuvable, prix non affiche, erreur reseau) : retourner un
    `PriceQuote` avec `price=None` et une `note` explicative a la place,
    meme discipline que `apps.core.services.whatsapp.WhatsAppClient`."""

    def fetch_price(self, target: PrcPriceWatchTarget) -> PriceQuote: ...


class StubPriceSourceProvider:
    """Provider par defaut, actif pour TOUTE plateforme tant qu'aucun
    connecteur reel n'est configure (cf. reserve de securite en tete de
    ce fichier). NE FAIT RIGOUREUSEMENT AUCUN APPEL RESEAU — ni `requests`,
    ni `urllib`, ni aucune autre bibliotheque HTTP n'est importee ou
    utilisee ici. Retourne systematiquement un `PriceQuote` sans prix,
    `is_stub=True`, avec une note invitant a configurer
    `settings.PRICE_WATCH_PROVIDERS` pour la plateforme concernee."""

    def fetch_price(self, target: PrcPriceWatchTarget) -> PriceQuote:
        return PriceQuote(
            price=None,
            currency=target.currency,
            is_stub=True,
            note=str(
                _(
                    "Connecteur non configure pour %(platform)s — fournir des "
                    "identifiants API officiels dans settings.PRICE_WATCH_PROVIDERS "
                    "(apres verification des CGU de la plateforme concernee)."
                )
                % {"platform": target.get_platform_code_display()}
            ),
        )


class GenericHttpPriceSourceProvider:
    """Squelette d'implementation REELLE minimale — JAMAIS instanciee par
    defaut (cf. reserve de securite en tete de ce fichier). Suppose une
    source de donnees LICITE deja negociee par l'utilisateur (API
    officielle de la plateforme, export contractuel, flux partenaire)
    exposant un endpoint GET renvoyant un prix pour une requete/reference
    donnee — PAS un scraping HTML de page publique. `api_key`/`base_url`
    proviennent de la configuration `settings.PRICE_WATCH_PROVIDERS[platform_code]`
    de l'utilisateur (cf. `get_provider_for_platform`), jamais d'une valeur
    codee en dur ici.

    **Activation sous la seule responsabilite de l'utilisateur** :
    instancier cette classe (via `PRICE_WATCH_PROVIDERS`) suppose d'avoir
    verifie au prealable que l'appel effectue respecte les CGU/le contrat
    de la plateforme visee. Ce squelette ne fournit aucune logique
    d'authentification/parsing specifique a une plateforme reelle — a
    completer par l'utilisateur au moment ou un vrai contrat/une vraie
    cle API est disponible."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def fetch_price(self, target: PrcPriceWatchTarget) -> PriceQuote:
        try:
            import requests  # import local — jamais charge tant que ce provider n'est pas instancie

            response = requests.get(
                self.base_url,
                params={"q": target.search_query_or_url},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            price = data.get("price")
            return PriceQuote(
                price=Decimal(str(price)) if price is not None else None,
                currency=data.get("currency", target.currency),
                is_stub=False,
                note=str(_("Relevé via connecteur configure (%(base_url)s)."))
                % {"base_url": self.base_url},
            )
        except Exception as exc:  # noqa: BLE001 — degrade en releve sans prix, jamais un crash
            return PriceQuote(
                price=None,
                currency=target.currency,
                is_stub=False,
                note=str(_("Échec du connecteur configure : %(error)s")) % {"error": str(exc)},
            )


def get_provider_for_platform(platform_code: str) -> PriceSourceProvider:
    """Retourne le provider actif pour `platform_code` : `StubPriceSource
    Provider` par defaut (aucune entree dans `settings.PRICE_WATCH_
    PROVIDERS`, ou entree incomplete/invalide), un `GenericHttpPriceSource
    Provider` construit a partir de la configuration UNIQUEMENT si
    l'utilisateur a explicitement rempli `base_url`+`api_key` pour cette
    plateforme. Ne resout jamais un connecteur "par convention" — silence
    radio de la configuration = stub, systematiquement."""
    from django.conf import settings

    providers_config = getattr(settings, "PRICE_WATCH_PROVIDERS", {}) or {}
    platform_config = providers_config.get(platform_code)
    if not platform_config:
        return StubPriceSourceProvider()

    base_url = platform_config.get("base_url")
    api_key = platform_config.get("api_key")
    if not base_url or not api_key:
        return StubPriceSourceProvider()

    return GenericHttpPriceSourceProvider(base_url=base_url, api_key=api_key)


def create_price_watch_target(
    *,
    tenant: Tenant,
    platform_code: str,
    search_query_or_url: str,
    currency: str = "MGA",
    frequency: str = PrcPriceWatchTarget.FREQUENCY_MONTHLY,
    material_reference_id: UUID | None = None,
    variant_id: UUID | None = None,
) -> PrcPriceWatchTarget:
    """Cree une cible de veille — exactement une reference produit doit
    etre fournie (`material_reference_id` XOR `variant_id`), jamais les
    deux, jamais aucune (cf. docstring de `PrcPriceWatchTarget`)."""
    if bool(material_reference_id) == bool(variant_id):
        raise ValueError(
            str(
                _(
                    "Une cible de veille doit reference exactement une reference "
                    "matiere OU une variante produit (jamais les deux, jamais aucune)."
                )
            )
        )
    return PrcPriceWatchTarget.objects.create(
        tenant=tenant,
        platform_code=platform_code,
        search_query_or_url=search_query_or_url,
        currency=currency,
        frequency=frequency,
        material_reference_id=material_reference_id,
        variant_id=variant_id,
    )


def _is_due(target: PrcPriceWatchTarget, now: dt.datetime) -> bool:
    last_snapshot_at = target.snapshots.aggregate(last=Max("observed_at"))["last"]
    if last_snapshot_at is None:
        return True
    interval = _FREQUENCY_TIMEDELTA.get(target.frequency, dt.timedelta(days=30))
    return bool(now - last_snapshot_at >= interval)


def check_price_watch_target(target: PrcPriceWatchTarget) -> PrcPriceSnapshot:
    """Interroge le provider actif pour `target.platform_code`, cree et
    retourne le nouveau `PrcPriceSnapshot` — jamais un declenchement de
    `PriceSourceProvider` en dehors de cette fonction et de `run_price_
    watch_checks` (surface unique d'appel reseau potentiel du module)."""
    provider = get_provider_for_platform(target.platform_code)
    quote = provider.fetch_price(target)
    return PrcPriceSnapshot.objects.create(
        tenant=target.tenant,
        target=target,
        observed_price=quote.price,
        observed_at=timezone.now(),
        source_note=quote.note,
        is_stub=quote.is_stub,
    )


def run_price_watch_checks(tenant: Tenant) -> list[dict[str, Any]]:
    """PRC3 : pour chaque `PrcPriceWatchTarget` active du tenant dont la
    frequence est echue (aucun releve encore, ou dernier `observed_at`
    plus vieux que l'intervalle de `frequency`, cf. `_is_due`), interroge
    le provider actif (stub par defaut, cf. reserve de securite en tete
    de ce fichier), cree un `PrcPriceSnapshot`, et — si un releve PRECEDENT
    existe ET que les deux releves portent un `observed_price` non nul —
    compare l'ecart relatif au seuil `PRICE_DEVIATION_ALERT_THRESHOLD_PCT`.
    Au-dela du seuil, notifie le role `acheteur` via `notify_role` (jamais
    un mecanisme d'alerte duplique).

    Retourne un resume par cible verifiee (liste de dict, jamais les
    objets ORM eux-memes — coherent avec le contrat "commande de
    management journalise un resume", meme discipline que
    `run_reordering`/`run_sales_recurrences`)."""
    now = timezone.now()
    results: list[dict[str, Any]] = []
    targets = PrcPriceWatchTarget.objects.filter(tenant=tenant, is_active=True)
    for target in targets:
        if not _is_due(target, now):
            continue

        previous_snapshot = target.snapshots.order_by("-observed_at").first()
        new_snapshot = check_price_watch_target(target)

        deviation_pct: Decimal | None = None
        if (
            previous_snapshot is not None
            and previous_snapshot.observed_price
            and new_snapshot.observed_price is not None
        ):
            deviation_pct = (
                abs(new_snapshot.observed_price - previous_snapshot.observed_price)
                / previous_snapshot.observed_price
                * Decimal(100)
            )
            if deviation_pct >= PRICE_DEVIATION_ALERT_THRESHOLD_PCT:
                notify_role(
                    str(tenant.id),
                    "acheteur",
                    "purchase.price_watch_deviation",
                    {
                        "target_id": str(target.id),
                        "platform_code": target.platform_code,
                        "search_query_or_url": target.search_query_or_url,
                        "previous_price": str(previous_snapshot.observed_price),
                        "new_price": str(new_snapshot.observed_price),
                        "deviation_pct": str(deviation_pct.quantize(Decimal("0.01"))),
                        "currency": target.currency,
                    },
                )

        results.append(
            {
                "target_id": target.id,
                "snapshot_id": new_snapshot.id,
                "observed_price": new_snapshot.observed_price,
                "is_stub": new_snapshot.is_stub,
                "deviation_pct": deviation_pct,
            }
        )
    return results
