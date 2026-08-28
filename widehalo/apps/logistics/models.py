"""Logistique (§5.7, cf. plan) : squelette (LOG1) — vehicules, documents
vehicule (RG-LOG-1, alerte avant expiration), couts vehicule, chauffeurs —
puis trajets/arrets (LOG2) : `LogTrip`/`LogTripStop` (RG-LOG-2 kilometrage,
RG-LOG-3 preuve de livraison, RG-LOG-4/LOG-TOUR1 suggestion d'ordre des
arrets) et `LogTripTemplate` (LOG-REC1, tournees recurrentes).

`LogDriver` porte le champ de consentement de geolocalisation
(`consent_geolocation`, LOG-GEO1) des sa creation plutot qu'ajoute apres
coup — LOG2 l'exploite pour refuser tout enregistrement de position sans
consentement explicite prealable (jamais suppose, jamais coche par
defaut) et pour masquer l'affichage hors heures de travail (cf.
`services/trips.py::get_stop_location`).

Regle de couplage n1 (identique a `sales`/`purchase`/`stocks`) : jamais de
FK Django vers une autre app metier. Les seuls FK "reels" hors `core` sont
`LogDriver.user` (compte applicatif optionnel du chauffeur) et
`LogTripStop.proof_document` (vers `core.Document`, RG-LOG-3) — `core` est
toujours autorise."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


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


class LogTrip(BaseModel, ReferenceMixin):
    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planifie"),
        (STATUS_IN_PROGRESS, "En cours"),
        (STATUS_COMPLETED, "Termine"),
        (STATUS_CANCELLED, "Annule"),
    ]

    vehicle = models.ForeignKey(LogVehicle, on_delete=models.PROTECT, related_name="trips")
    driver = models.ForeignKey(LogDriver, on_delete=models.PROTECT, related_name="trips")
    date = models.DateField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    # RG-LOG-2 : kilometrage du trajet — alimente `LogVehicle.odometer_km`
    # (et, indirectement, le cout/km) a la cloture du trajet.
    start_odometer_km = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    end_odometer_km = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Gabarit d'origine si ce trajet a ete genere par une recurrence
    # (LOG-REC1) — jamais obligatoire, un trajet peut etre cree directement.
    template = models.ForeignKey(
        "LogTripTemplate", null=True, blank=True, on_delete=models.SET_NULL, related_name="trips"
    )

    class Meta:
        db_table = "log_trip"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class LogTripStop(BaseModel):
    TYPE_PICKUP = "pickup"
    TYPE_DROPOFF = "dropoff"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_PICKUP, "Enlevement"),
        (TYPE_DROPOFF, "Livraison"),
        (TYPE_OTHER, "Autre"),
    ]

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_COMPLETED, "Termine"),
    ]

    trip = models.ForeignKey(LogTrip, on_delete=models.CASCADE, related_name="stops")
    sequence = models.PositiveIntegerField()
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_DROPOFF)
    address = models.CharField(max_length=255)
    # RG-LOG-4/LOG-TOUR1 : coordonnees utilisees uniquement pour la
    # SUGGESTION d'ordre des arrets (plus-proche-voisin) et, si le
    # chauffeur y a explicitement consenti (`LogDriver.consent_geolocation`),
    # pour la position reellement enregistree a l'arrivee — jamais
    # obligatoires (un arret peut n'avoir qu'une adresse texte).
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    planned_time = models.DateTimeField(null=True, blank=True)
    actual_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # RG-LOG-3 : preuve de livraison (signature/photo horodatee) — reutilise
    # `core.services.documents.store_document`, jamais un stockage de
    # fichier ad hoc.
    proof_document = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    signed_by = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "log_trip_stop"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "sequence"], name="uniq_log_trip_stop_sequence")
        ]

    def __str__(self) -> str:
        return f"{self.trip} — arret {self.sequence}"


class LogTripTemplate(BaseModel):
    """LOG-REC1 : tournee recurrente — genere un `LogTrip` en `planned` a
    echeance, jamais confirme/demarre automatiquement (meme discipline que
    `SalesRecurrence`/`PurReorderingRule`). `stops_data` est une liste de
    dicts JSON (`address`/`type`/`latitude`/`longitude`) copies tels quels
    dans les `LogTripStop` du trajet genere — pas de FK vers un arret
    modele separe, la recurrence n'a de sens qu'au niveau du trajet entier."""

    INTERVAL_WEEKLY = "weekly"
    INTERVAL_MONTHLY = "monthly"
    INTERVAL_CHOICES = [
        (INTERVAL_WEEKLY, "Hebdomadaire"),
        (INTERVAL_MONTHLY, "Mensuelle"),
    ]

    name = models.CharField(max_length=150)
    vehicle = models.ForeignKey(LogVehicle, on_delete=models.PROTECT, related_name="+")
    driver = models.ForeignKey(LogDriver, on_delete=models.PROTECT, related_name="+")
    interval = models.CharField(max_length=16, choices=INTERVAL_CHOICES, default=INTERVAL_WEEKLY)
    stops_data = models.JSONField(default=list)
    next_run = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "log_trip_template"

    def __str__(self) -> str:
        return self.name
