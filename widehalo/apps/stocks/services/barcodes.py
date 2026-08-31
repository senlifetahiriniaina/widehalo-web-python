"""Codes-barres et QR (STK-BC1, §5.8, ST7 du sous-sequencement `stocks` —
cf. plan) : "Generation d'etiquettes code-barres/QR pour emplacements,
lots et produits" (CDC, enrichissement "Adopter"/"Adapter", cf. section
"Decisions de sequencement" du plan).

**Perimetre assume — `stocks` ne couvre ici que `StkLocation`/`StkLot`,
jamais un produit `catalog`** : le CDC dit "emplacements, lots ET
produits", mais `stocks` ne peut jamais faire de FK Django ni ajouter de
champ a `apps.catalog.models.ProductVariant` (regle de couplage n°1, app
distincte, hors perimetre de migration de CE module). Le code-barres
PRODUIT est donc documente ici comme un GAP volontairement non comble par
ce module — un futur besoin cote `catalog` devra y ajouter son propre
champ/service, `stocks` ne peut pas le faire a sa place. `StkLocation`
(deja pourvue d'un champ `barcode` depuis ST1) et `StkLot` (champ
`barcode` ajoute dans ce meme ST7, cf. `models.py`) sont en revanche des
entites `stocks`-owned : le perimetre normal de ce module.

**`qrcode` — PREMIER usage reel de cette dependance dans ce depot**
(`requirements/base.txt`, deja declaree mais jamais utilisee jusqu'a ce
ST7, verifie explicitement par recherche avant d'ecrire ce module).

**Format du code-barres (`generate_barcode_value`)** : le CDC ne precise
AUCUNE symbologie ni format de code-barres reel (EAN/GS1/Code128...) — une
simplification assumee est retenue ici : une chaine alphanumerique
deterministe `"{PREFIX}-{IDENTIFIANT}"` (majuscule), pensee pour etre
encodee dans un QR (scan camera → lookup interne, `lookup_by_barcode`
ci-dessous), PAS un vrai code-barres standard scannable par un lecteur
laser generique. Documente ici comme limitation assumee, pas une omission."""

from __future__ import annotations

import io

import qrcode
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLocation, StkLot


def generate_barcode_value(*, prefix: str, identifier: str) -> str:
    """Valeur deterministe `"{PREFIX}-{IDENTIFIANT}"` (majuscule) — cf.
    docstring de module pour la justification de ce format simplifie.
    Meme entree → toujours la meme valeur (pas d'alea/sequence), ce qui
    permet de la regenerer a l'identique si besoin (ex. reimpression
    d'etiquette) sans avoir a la stocker ailleurs que sur l'entite elle
    meme."""
    return f"{prefix}-{identifier}".upper()


def generate_qr_code_png(value: str) -> bytes:
    """Rend `value` en QR code PNG — bytes purs, aucune ecriture disque ni
    couplage a `core.services.documents.store_document` (laisse a un futur
    appelant ecrans/API qui voudra attacher/servir cette image, hors
    perimetre backend de ce ST, cf. plan ST7/ST8)."""
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def set_location_barcode(location: StkLocation, *, value: str | None = None) -> StkLocation:
    """Fixe `StkLocation.barcode` a `value`, ou l'auto-genere
    (`generate_barcode_value(prefix="LOC", identifier=location.code)`)
    quand `value` est omis. Refuse (`ValidationError`, garde de SERVICE —
    pas de contrainte DB, cf. justification ci-dessous) si un AUTRE
    emplacement ACTIF du meme tenant porte deja exactement cette valeur.

    **Pourquoi une garde de service plutot qu'un `UniqueConstraint` DB** :
    un `UniqueConstraint` sur un champ nullable/blank par defaut
    (`StkLocation.barcode`, vide pour la quasi-totalite des emplacements
    qui n'ont jamais ete etiquetes) collisionnerait sur la chaine vide des
    le deuxieme emplacement sans code-barres — il faudrait alors une
    contrainte partielle (`condition=~models.Q(barcode=""))`, sans aucun
    precedent d'index partiel dans ce depot a ce jour, cf. docstring
    `StkNegativeStockException`) juste pour un besoin d'unicite qui n'est
    PAS critique-securite comme `AccAccount.code` (un code-barres sert au
    confort du scan camera, pas a une integrite comptable/financiere) — la
    garde applicative est proportionnee a cet enjeu."""
    resolved_value = (
        value
        if value is not None
        else generate_barcode_value(prefix="LOC", identifier=location.code)
    )
    conflict = (
        StkLocation.objects.filter(tenant=location.tenant, barcode=resolved_value, is_active=True)
        .exclude(pk=location.pk)
        .exists()
    )
    if conflict:
        raise ValidationError(
            _("Un autre emplacement actif porte déjà ce code-barres : %(value)s")
            % {"value": resolved_value}
        )
    location.barcode = resolved_value
    location.save(update_fields=["barcode"])
    return location


def lookup_by_barcode(tenant: Tenant, barcode_value: str) -> StkLocation | None:
    """Lecture inverse (scan camera → emplacement) — restreinte aux
    emplacements ACTIFS du tenant fourni. `stocks` n'expose ici QUE le
    lookup emplacement (cf. docstring de module pour `StkLot`, dote de son
    propre `lookup_lot_by_barcode` ci-dessous plutot que d'une signature
    unique polymorphe — deux entites distinctes, deux fonctions de lookup
    distinctes, meme discipline de nommage explicite que le reste de ce
    module)."""
    return StkLocation.objects.filter(tenant=tenant, barcode=barcode_value, is_active=True).first()


def set_lot_barcode(lot: StkLot, *, value: str | None = None) -> StkLot:
    """Equivalent EXACT de `set_location_barcode` pour `StkLot` — meme
    format par defaut (`prefix="LOT"`, `identifier=lot.name`, le nom de
    lot etant son identifiant metier, cf. docstring `StkLot`), meme garde
    de service (jamais de contrainte DB, meme justification que
    ci-dessus)."""
    resolved_value = (
        value if value is not None else generate_barcode_value(prefix="LOT", identifier=lot.name)
    )
    conflict = (
        StkLot.objects.filter(tenant=lot.tenant, barcode=resolved_value, is_active=True)
        .exclude(pk=lot.pk)
        .exists()
    )
    if conflict:
        raise ValidationError(
            _("Un autre lot actif porte déjà ce code-barres : %(value)s")
            % {"value": resolved_value}
        )
    lot.barcode = resolved_value
    lot.save(update_fields=["barcode"])
    return lot


def lookup_lot_by_barcode(tenant: Tenant, barcode_value: str) -> StkLot | None:
    """Lecture inverse (scan camera → lot) — meme discipline exacte que
    `lookup_by_barcode` ci-dessus, restreinte aux lots ACTIFS du tenant
    fourni."""
    return StkLot.objects.filter(tenant=tenant, barcode=barcode_value, is_active=True).first()
