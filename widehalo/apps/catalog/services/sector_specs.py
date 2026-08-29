"""SEC1 (extension sectorielle Madagascar, cf. plan) : validation par
secteur du contenu `CatalogSectorSpec.attributes`.

Un petit dictionnaire de validateurs Python par `sector_code`, PAS un
moteur JSON Schema generique — simplification deliberee, coherente avec le
choix deja fait pour `TextileSpec.composition` (JSONB libre). Chaque
validateur controle uniquement la presence et le type grossier des cles
attendues, jamais un referentiel metier exhaustif (ex : pas de liste
fermee de types de tannage ou d'allergenes reconnus) — le contenu
indicatif ci-dessous, comme chaque fixture metier deja livree dans ce
projet (PCG 2005, benchmarks textile...), est une reserve non-experte, non
validee par un expert sectoriel independant (cuir, agroalimentaire,
artisanat).

`import_export` n'a volontairement AUCUN validateur ici (ni entree dans
`CatalogSectorSpec.SECTOR_CHOICES`) : c'est deja le cas d'usage par defaut
de `purchase`/`stocks`/`sales`/`logistics` (negoce sans transformation),
confirme par audit prealable — zero code sectoriel necessaire pour ce
secteur (cf. plan)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.catalog.models import CatalogSectorSpec, ProductVariant

_TANNAGE_VEGETAL = "vegetal"
_TANNAGE_CHROME = "chrome"


def _validate_cuir(attributes: dict[str, Any]) -> None:
    """Cuir & maroquinerie : type de peau, tannage (vegetal/chrome),
    epaisseur (mm), grade qualite — contenu indicatif, cf. docstring
    module."""
    if not attributes.get("type_peau"):
        raise ValidationError(_("Cuir : le type de peau (`type_peau`) est obligatoire."))
    if attributes.get("tannage") not in (_TANNAGE_VEGETAL, _TANNAGE_CHROME):
        raise ValidationError(_("Cuir : le tannage (`tannage`) doit valoir 'vegetal' ou 'chrome'."))
    epaisseur_mm = attributes.get("epaisseur_mm")
    if epaisseur_mm is not None:
        try:
            valeur = float(epaisseur_mm)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("Cuir : l'epaisseur (`epaisseur_mm`) doit etre un nombre.")
            ) from exc
        if valeur <= 0:
            raise ValidationError(
                _("Cuir : l'epaisseur (`epaisseur_mm`) doit etre strictement positive.")
            )


def _validate_agroalimentaire(attributes: dict[str, Any]) -> None:
    """Agroalimentaire : composition, allergenes, information
    nutritionnelle, conditions de conservation — volontairement redondant
    a minima avec `stocks.StkLot` (peremption/tracabilite par lot
    physique reel) : cette fiche documente le produit statique du
    catalogue, `StkLot` la traçabilite par lot, aucune duplication de
    mecanisme (cf. plan)."""
    if not attributes.get("conditions_conservation"):
        raise ValidationError(
            _(
                "Agroalimentaire : les conditions de conservation "
                "(`conditions_conservation`) sont obligatoires."
            )
        )
    allergenes = attributes.get("allergenes", [])
    if not isinstance(allergenes, list):
        raise ValidationError(_("Agroalimentaire : `allergenes` doit etre une liste."))
    composition = attributes.get("composition", {})
    if not isinstance(composition, dict):
        raise ValidationError(_("Agroalimentaire : `composition` doit etre un objet JSON."))
    information_nutritionnelle = attributes.get("information_nutritionnelle", {})
    if not isinstance(information_nutritionnelle, dict):
        raise ValidationError(
            _("Agroalimentaire : `information_nutritionnelle` doit etre un objet JSON.")
        )


def _validate_artisanat(attributes: dict[str, Any]) -> None:
    """Artisanat : matiere premiere, technique, origine/artisan (texte
    libre, pas de FK vers un futur registre d'artisans — hors perimetre,
    cf. plan)."""
    if not attributes.get("matiere_premiere"):
        raise ValidationError(
            _("Artisanat : la matiere premiere (`matiere_premiere`) est obligatoire.")
        )
    if not attributes.get("technique"):
        raise ValidationError(_("Artisanat : la technique (`technique`) est obligatoire."))


_VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    CatalogSectorSpec.SECTOR_CUIR: _validate_cuir,
    CatalogSectorSpec.SECTOR_AGROALIMENTAIRE: _validate_agroalimentaire,
    CatalogSectorSpec.SECTOR_ARTISANAT: _validate_artisanat,
}


def validate_sector_attributes(sector_code: str, attributes: dict[str, Any]) -> None:
    """Leve `ValidationError` (i18n) si `attributes` ne respecte pas le
    schema indicatif du secteur `sector_code`, ou si `sector_code` n'est
    pas l'un des 3 secteurs geres ici (jamais `import_export`, cf.
    docstring module)."""
    validator = _VALIDATORS.get(sector_code)
    if validator is None:
        raise ValidationError(
            _("Secteur inconnu pour une fiche sectorielle : %(sector_code)s")
            % {"sector_code": sector_code}
        )
    validator(attributes)


def create_sector_spec(
    variant: ProductVariant, *, sector_code: str, attributes: dict[str, Any]
) -> CatalogSectorSpec:
    """Point d'entree unique de creation d'une `CatalogSectorSpec` — valide
    toujours `attributes` avant persistance (jamais de creation directe
    depuis une vue/API, meme discipline que les autres services `catalog`)."""
    validate_sector_attributes(sector_code, attributes)
    spec = CatalogSectorSpec(
        tenant=variant.tenant,
        variant=variant,
        sector_code=sector_code,
        attributes=attributes,
    )
    spec.full_clean()
    spec.save()
    return spec
