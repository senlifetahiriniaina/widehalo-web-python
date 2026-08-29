"""Registre de risques operationnels generique (RSK1-2, chantier « etudes de
faisabilite, veille prix, capacite 90j, risques, qualite, UI/UX »).

`RiskItem` vit dans `core` (comme `Document`/`ApprovalRequest`) car il doit
etre rattachable a N'IMPORTE QUELLE entite de N'IMPORTE QUEL module
(`PurOrder`, `LogShipment`, `MrpOrder`, `FinLoanApplication`...) via
`content_type`/`object_id` (GenericForeignKey standard) — un module metier
n'a jamais besoin d'importer ce modele pour l'utiliser directement, seul un
futur `apps.<module>.views`/`apps.<module>.services` construira un lien
"Signaler un risque" pointant vers l'ecran generique de `core` (regle de
couplage n°5, aucune exception).

**Rattachement optionnel (choix assume)** : `content_type`/`object_id` sont
nullables, memes choix que `Document` (`content_type` `null=True,
blank=True`, `object_id` `CharField(blank=True)`). Un risque purement
"generique", sans document/commande/lot precis a designer (ex. "risque de
change global sur les achats en devises", "risque reglementaire sectoriel"),
est un cas d'usage reel du CDC (§4 du chantier: "structurer la gestion des
risques operationnels") — imposer un rattachement obligatoire aurait exclu
ce cas sans qu'aucune exigence explicite ne le demande.

**Score derive, jamais saisi (choix assume)** : `score = likelihood *
impact` est recalcule par `apps.core.services.risk` (jamais dans un
`save()` de modele) — meme discipline que le reste du projet, ou tout
champ derive (ex. `MrpOrder`/`StkQuant`, cf. docstrings de leurs modules)
est recalcule cote service plutot que dans une surcharge de `Model.save()`.
Consequence assumee : une ecriture qui contournerait le service (ex. admin
Django brut) pourrait laisser un `score` non recalcule — meme compromis que
partout ailleurs dans le socle, le service est le point d'entree normatif,
pas une garantie au niveau SGBD."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel

CATEGORY_SUPPLIER = "fournisseur"
CATEGORY_PRODUCTION = "production"
CATEGORY_LOGISTICS = "logistique"
CATEGORY_FINANCIAL = "financier"
CATEGORY_QUALITY = "qualite"
CATEGORY_HR = "rh"
CATEGORY_OTHER = "autre"
CATEGORY_CHOICES = [
    (CATEGORY_SUPPLIER, _("Fournisseur")),
    (CATEGORY_PRODUCTION, _("Production")),
    (CATEGORY_LOGISTICS, _("Logistique")),
    (CATEGORY_FINANCIAL, _("Financier")),
    (CATEGORY_QUALITY, _("Qualite")),
    (CATEGORY_HR, _("Ressources humaines")),
    (CATEGORY_OTHER, _("Autre")),
]

STATUS_OPEN = "open"
STATUS_MITIGATING = "mitigating"
STATUS_CLOSED = "closed"
STATUS_CHOICES = [
    (STATUS_OPEN, _("Ouvert")),
    (STATUS_MITIGATING, _("En attenuation")),
    (STATUS_CLOSED, _("Cloture")),
]

# Seuil de publication de l'evenement `risk.flagged` (score >= seuil). Sur
# une echelle 1-5 x 1-5 (1-25), 15 correspond au premier palier ou AU MOINS
# un des deux facteurs est "eleve" (4 ou 5) ET l'autre au moins "moyen-haut"
# (ex. 5x3, 4x4, 5x4, 5x5) — repere usuel de matrice de risques (zone
# rouge/orange haute), choisi ici comme seuil raisonnable documente plutot
# qu'une valeur arbitraire non justifiee. Reutilise par
# `apps.core.services.risk` (seule source de verite, importe depuis ce
# module pour eviter toute divergence entre le modele et le service).
HIGH_SCORE_THRESHOLD = 15


class RiskItem(BaseModel):
    """Enregistrement de suivi (pas un document numerote : pas de
    `ReferenceMixin`) representant un risque operationnel identifie, avec
    son evaluation (probabilite x impact) et son plan d'attenuation."""

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER)
    likelihood = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    impact = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    # Derive de likelihood*impact — jamais assigne directement par un
    # appelant (cf. docstring de module) : recalcule inconditionnellement
    # dans save().
    score = models.PositiveSmallIntegerField(default=0, editable=False)
    mitigation_plan = models.TextField(blank=True)
    owner = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="owned_risks")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    review_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "core_risk_item"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.get_category_display()} ({self.likelihood}x{self.impact}={self.score})"
