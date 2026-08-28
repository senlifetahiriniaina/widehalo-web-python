"""Logistique (§5.7, LOG1 du sous-sequencement `logistics` — cf. plan) :
squelette du module — vehicules, documents vehicule (RG-LOG-1, alerte
avant expiration), couts vehicule, chauffeurs.

`LogDriver` porte le champ de consentement de geolocalisation
(`consent_geolocation`, LOG-GEO1) des sa creation plutot qu'ajoute apres
coup — LOG2 (trajets/arrets) l'exploitera pour masquer la position hors
heures de travail et appliquer une politique de retention, mais le champ
lui-meme appartient logiquement au chauffeur, pas au trajet.

Regle de couplage n1 (identique a `sales`/`purchase`/`stocks`) : jamais de
FK Django vers une autre app metier. Le seul FK "reel" hors `core` est
`LogDriver.user` vers `core.User` (compte applicatif optionnel du
chauffeur, pour lui permettre de se connecter et remplir un CRA de
livraison plus tard) — `core` est toujours autorise."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class LogVehicle(BaseModel):
    TYPE_TRUCK = "truck"
    TYPE_VAN = "van"
    TYPE_MOTORCYCLE = "motorcycle"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_TRUCK, "Camion"),
        (TYPE_VAN, "Camionnette"),
        (TYPE_MOTORCYCLE, "Moto"),
        (TYPE_OTHER, "Autre"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_RETIRED = "retired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "En service"),
        (STATUS_MAINTENANCE, "En maintenance"),
        (STATUS_RETIRED, "Retire"),
    ]

    plate_number = models.CharField(max_length=32)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_TRUCK)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    capacity_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    capacity_m3 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Alimente par RG-LOG-2 (LOG2) a chaque trajet cloture — champ pose ici
    # car il appartient au vehicule, pas au trajet.
    odometer_km = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "log_vehicle"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "plate_number"], name="uniq_log_vehicle_plate_number"
            )
        ]

    def __str__(self) -> str:
        return self.plate_number


class LogVehicleDocument(BaseModel):
    TYPE_INSURANCE = "insurance"
    TYPE_REGISTRATION = "registration"
    TYPE_TECHNICAL_INSPECTION = "technical_inspection"
    TYPE_PERMIT = "permit"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_INSURANCE, "Assurance"),
        (TYPE_REGISTRATION, "Carte grise"),
        (TYPE_TECHNICAL_INSPECTION, "Visite technique"),
        (TYPE_PERMIT, "Autorisation/permis"),
        (TYPE_OTHER, "Autre"),
    ]

    vehicle = models.ForeignKey(LogVehicle, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    reference = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    # RG-LOG-1 : delai (en jours) avant `expiry_date` a partir duquel une
    # alerte doit etre remontee — parametrable par document, pas un seuil
    # global unique (un document d'assurance et une visite technique n'ont
    # pas necessairement le meme delai de renouvellement pratique).
    alert_days_before = models.PositiveSmallIntegerField(default=30)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "log_vehicle_document"
        indexes = [models.Index(fields=["tenant", "expiry_date"])]

    def __str__(self) -> str:
        return f"{self.vehicle.plate_number} — {self.get_doc_type_display()}"


class LogVehicleCost(BaseModel):
    TYPE_FUEL = "fuel"
    TYPE_MAINTENANCE = "maintenance"
    TYPE_INSURANCE = "insurance"
    TYPE_TOLL = "toll"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_FUEL, "Carburant"),
        (TYPE_MAINTENANCE, "Entretien"),
        (TYPE_INSURANCE, "Assurance"),
        (TYPE_TOLL, "Peage"),
        (TYPE_OTHER, "Autre"),
    ]

    vehicle = models.ForeignKey(LogVehicle, on_delete=models.CASCADE, related_name="costs")
    date = models.DateField()
    cost_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    amount_mga = models.DecimalField(max_digits=18, decimal_places=4)
    odometer_km = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "log_vehicle_cost"
        indexes = [models.Index(fields=["tenant", "vehicle", "date"])]

    def __str__(self) -> str:
        return f"{self.vehicle.plate_number} — {self.get_cost_type_display()} — {self.amount_mga}"


class LogDriver(BaseModel):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=32, blank=True)
    license_number = models.CharField(max_length=64, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    # Compte applicatif optionnel — un chauffeur n'a pas necessairement de
    # session WideHalo (ex. transporteur externe occasionnel).
    user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # LOG-GEO1 : consentement explicite requis avant toute collecte de
    # position (`LogTripStop.latitude/longitude`, LOG2) — jamais suppose,
    # jamais coche par defaut.
    consent_geolocation = models.BooleanField(default=False)

    class Meta:
        db_table = "log_driver"

    def __str__(self) -> str:
        return self.name
