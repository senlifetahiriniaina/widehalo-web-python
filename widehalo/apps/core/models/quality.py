"""Qualite generique : gabarits de controle et inspections (QLT1-2, chantier
« etudes de faisabilite, veille prix, capacite 90j, risques, qualite,
UI/UX », §5 « Qualite : preparation, controle, suivi, certifications »).

`QltChecklistTemplate`/`QltInspection` vivent dans `core` — meme patron
direct que `RiskItem` (`apps.core.models.risk`, RSK1-2, livre juste avant ce
lot) : `QltInspection` doit etre rattachable a N'IMPORTE QUELLE entite de
N'IMPORTE QUEL module (`StkLot`, `PurReceiptLine`, `MrpOrder`...) via
`content_type`/`object_id` (GenericForeignKey Django standard), sans qu'un
module metier n'ait jamais besoin d'importer ce modele pour l'utiliser
directement — seul un futur `apps.<module>.views`/`apps.<module>.services`
construira un lien "Lancer une inspection qualite" pointant vers l'ecran
generique de `core` (regle de couplage n°5, aucune exception).

**Rattachement optionnel (choix assume, meme raisonnement que `RiskItem`)** :
`content_type`/`object_id` sont nullables — un gabarit peut etre applique
"a blanc" (formation, audit interne generique) sans entite precise a
designer. Aucune exigence explicite n'impose un rattachement obligatoire.

**`passed` derive, jamais saisi (choix assume, meme discipline que
`RiskItem.score`)** : calcule par `apps.core.services.quality` a partir de
`results` (jamais dans un `save()` de modele) — recalcule inconditionnellement
a chaque creation/mise a jour cote service. Regle exacte : `passed=True`
ssi AUCUN critere de `results` n'a le statut `NONCONFORME` (un
`OBSERVATION` seul, sans non-conformite, ne fait pas echouer l'inspection —
c'est une remarque, pas un rejet). Consequence assumee : une ecriture qui
contournerait le service (ex. admin Django brut) pourrait laisser `passed`
non recalcule — meme compromis que partout ailleurs dans le socle.

**Decision D5 (Bloc D, cf. addendum de `docs/planning/2026-09-adr-qualite-
haccp-app-dediee.md`) : ces deux modeles RESTENT tels quels, aucune
migration/retrait.** Aucune cible de migration compatible n'existe dans
`apps.quality` — son seul modele de "verdict" (`QltMeasurement`) est
strictement numerique (valeur vs. limites), alors que ces deux modeles
sont qualitatifs (critere -> conforme/non-conforme/observation). Le gap
de navigation deja disclose ci-dessus (aucun lien depuis un autre ecran
du produit) reste ouvert — probleme distinct, hors perimetre de la
decision D5 (qui portait sur migration/retrait, pas raccordement UI)."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel

# Alignes sur les codes secteur deja utilises par
# `catalog.CatalogSectorSpec`/`strategy.StgSectorBenchmark` — `core` ne peut
# pas importer ces modeles (couplage inter-app strict), donc les codes sont
# ici de simples chaines libres documentees, jamais une FK ni un import de
# leurs `choices`.
SECTOR_TEXTILE = "textile"
SECTOR_CUIR = "cuir"
SECTOR_AGROALIMENTAIRE = "agroalimentaire"
SECTOR_IMPORT_EXPORT = "import_export"
SECTOR_ARTISANAT = "artisanat"
SECTOR_CHOICES = [
    (SECTOR_TEXTILE, _("Textile")),
    (SECTOR_CUIR, _("Cuir & maroquinerie")),
    (SECTOR_AGROALIMENTAIRE, _("Agroalimentaire")),
    (SECTOR_IMPORT_EXPORT, _("Import-export")),
    (SECTOR_ARTISANAT, _("Artisanat")),
]

# Statut d'un critere de controle dans `QltInspection.results` (liste de
# dicts `{"code": ..., "status": ..., "comment": ...}`) — pas un choices de
# champ de modele (results est un JSONField libre), documente ici pour
# etre la seule source de verite partagee entre le service et les ecrans/
# templates qui construisent le formulaire de saisie.
RESULT_CONFORME = "conforme"
RESULT_NONCONFORME = "non_conforme"
RESULT_OBSERVATION = "observation"
RESULT_STATUS_CHOICES = [
    (RESULT_CONFORME, _("Conforme")),
    (RESULT_NONCONFORME, _("Non conforme")),
    (RESULT_OBSERVATION, _("Observation")),
]


class QltChecklistTemplate(BaseModel):
    """Gabarit reutilisable de criteres de controle qualite. `items` est une
    liste JSON de criteres, ex. `[{"code": "COUTURE-1", "label": "Solidite
    des coutures", "expected": "Aucun fil apparent"}, ...]` — meme choix
    JSONB libre (pas de moteur de schema formel) que
    `catalog.CatalogSectorSpec.attributes`/`mrp.MrpBomLine.qty_by_size`,
    disclosed et coherent avec le reste du socle."""

    name = models.CharField(max_length=200)
    sector_code = models.CharField(max_length=20, choices=SECTOR_CHOICES, blank=True)
    items = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "core_qlt_checklist_template"

    def __str__(self) -> str:
        return self.name


class QltInspection(BaseModel):
    """Enregistrement de suivi (pas un document numerote : pas de
    `ReferenceMixin`) representant une inspection qualite realisee a partir
    d'un `QltChecklistTemplate`, avec son resultat par critere et son
    verdict global derive."""

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    template = models.ForeignKey(
        QltChecklistTemplate, on_delete=models.PROTECT, related_name="inspections"
    )
    # Liste JSON, une entree par critere de `template.items` :
    # `[{"code": "COUTURE-1", "status": "conforme"|"non_conforme"|
    # "observation", "comment": "..."}]` — cf. `RESULT_STATUS_CHOICES`.
    results = models.JSONField(default=list, blank=True)
    # Derive de `results` — jamais assigne directement par un appelant (cf.
    # docstring de module) : recalcule inconditionnellement par le service.
    passed = models.BooleanField(default=True, editable=False)
    inspector = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="qlt_inspections"
    )
    inspected_at = models.DateTimeField()

    class Meta:
        db_table = "core_qlt_inspection"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.template.name} ({'OK' if self.passed else 'KO'})"
