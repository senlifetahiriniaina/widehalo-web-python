"""Logistique (§5.7, cf. plan) : squelette (LOG1) — vehicules, documents
vehicule (RG-LOG-1, alerte avant expiration), couts vehicule, chauffeurs —
puis trajets/arrets (LOG2) : `LogTrip`/`LogTripStop` (RG-LOG-2 kilometrage,
RG-LOG-3 preuve de livraison, RG-LOG-4/LOG-TOUR1 suggestion d'ordre des
arrets) et `LogTripTemplate` (LOG-REC1, tournees recurrentes) — puis
emballages/prestataires/tarifs de fret (LOG3, cf. plus bas).

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
toujours autorise. `LogPackagingPlan.source` (LOG3) est une reference
GENERIQUE (`content_type`/`object_id`, memes noms de champ que
`core.Document`/`core.SearchIndex`/`core.StateTransition` — requis pour
que `tenant_export.import_tenant_archive()` et le test parametrique
T3 (`test_tenant_portability_per_entity.py`), qui reconnaissent une paire
GenericForeignKey a son NOM DE CHAMP litteral, la traitent correctement)
au document d'origine (un `LogTrip` aujourd'hui, un futur `LogShipment` a
partir de LOG4) — jamais une FK directe, pour ne pas figer ce plan
d'emballage a un seul type de document."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django_fsm import FSMField, transition

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


class LogPackagingType(BaseModel):
    """LOG3 : contenant physique reutilisable (carton, palette, sac...) —
    distinct du conditionnement produit (`catalog.Packaging`, combien
    d'unites tiennent DANS un colis) : ce modele decrit le colis
    lui-meme (poids/volume a vide, capacite max)."""

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    tare_weight_kg = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    max_weight_kg = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    volume_m3 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "log_packaging_type"

    def __str__(self) -> str:
        return self.name


class LogPackagingPlan(BaseModel, ReferenceMixin):
    """RG-LOG-5 : plan d'emballage calcule pour un document source
    quelconque (`source_content_type`/`source_object_id`) — voir docstring
    de tete de fichier pour le choix d'une reference generique plutot
    qu'une FK directe."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    source = GenericForeignKey("content_type", "object_id")
    total_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    total_volume_m3 = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    class Meta:
        db_table = "log_packaging_plan"
        indexes = [models.Index(fields=["tenant", "content_type", "object_id"])]

    def __str__(self) -> str:
        return self.reference or str(self.id)


class LogPackagingPlanLine(BaseModel):
    plan = models.ForeignKey(LogPackagingPlan, on_delete=models.CASCADE, related_name="lines")
    packaging_type = models.ForeignKey(LogPackagingType, on_delete=models.PROTECT, related_name="+")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — regle
    # de couplage n1, resolu via `catalog.services.public` quand necessaire.
    variant_id = models.UUIDField()
    qty_units = models.DecimalField(max_digits=12, decimal_places=3)
    qty_packages = models.PositiveIntegerField()

    class Meta:
        db_table = "log_packaging_plan_line"


class LogServiceProvider(BaseModel):
    TYPE_CARRIER = "carrier"
    TYPE_CUSTOMS_BROKER = "customs_broker"
    TYPE_HANDLING = "handling"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_CARRIER, "Transporteur"),
        (TYPE_CUSTOMS_BROKER, "Transitaire/douane"),
        (TYPE_HANDLING, "Manutention"),
        (TYPE_OTHER, "Autre"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_CARRIER)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)
    # PT8 (chantier "fiche partenaire a onglets par role") : jusqu'ici
    # `LogServiceProvider` etait un annuaire totalement autonome, jamais
    # relie a `apps.partners.models.Partner` (aucun champ de ce module ne
    # referencait un partenaire, verifie en lisant ce fichier avant
    # d'ecrire quoi que ce soit — deviation par rapport au plan qui
    # supposait un champ deja existant du style `carrier_partner_id`).
    # Ajoute nullable, sans migration de donnees (memes discipline que
    # `catalog.ProductSupplierInfo.priority`/`origin`/`min_qty`, PU2) :
    # les prestataires existants restent `None` jusqu'a rattachement
    # manuel a un `Partner` (role `carrier`) depuis l'onglet
    # "Transporteur". UUID nu, JAMAIS une FK Django vers
    # `apps.partners.models.Partner` (regle de couplage n°1).
    partner_id = models.UUIDField(null=True, blank=True)
    # LOG6/API-6 : secret partage pour verifier la signature HMAC des
    # webhooks entrants de ce transporteur (`services/webhooks.py`) —
    # aucun mecanisme de signature HMAC generalise n'existait ailleurs
    # dans ce depot avant ce lot (le webhook WhatsApp du Lot 1 utilise le
    # mecanisme propre a l'API Meta Cloud, pas un HMAC generique). Vide
    # par defaut : un transporteur sans webhook configure n'en a pas
    # besoin.
    webhook_secret = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "log_service_provider"

    def __str__(self) -> str:
        return self.name


class LogFreightTariff(BaseModel):
    """LOG3 : grille tarifaire declarative d'un prestataire — jamais
    d'appel API transporteur reel (adaptation explicite du CDC, cf. plan) ;
    `services/freight.py::compare_freight_tariffs` classe les tarifs
    valides pour une paire origine/destination par cout puis delai."""

    provider = models.ForeignKey(
        LogServiceProvider, on_delete=models.CASCADE, related_name="tariffs"
    )
    origin = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    price_mga = models.DecimalField(max_digits=18, decimal_places=4)
    price_per_kg_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    transit_days = models.PositiveSmallIntegerField()
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "log_freight_tariff"
        indexes = [models.Index(fields=["tenant", "origin", "destination"])]

    def __str__(self) -> str:
        return f"{self.provider.name} — {self.origin} -> {self.destination}"


class LogShipment(BaseModel, ReferenceMixin):
    """LOG4 : expedition — machine a etats complete (`django-fsm-2`,
    `attempt_transition()` du socle, meme discipline que `PurOrder`/
    `SalesOrder`). Le diagramme du CDC (§5.7.4) decrit un cycle en une
    seule chaine (prevue -> reservee -> enlevee -> en transit -> arrivee au
    port -> en dedouanement -> dedouanee -> livree -> cloturee, branche
    bloquee) : un seul champ FSM suffit, meme simplification assumee que
    `PurOrder.state`/`SalesOrder.state` (cf. leurs docstrings).

    `purchase_order_ids`/`sales_order_ids` : listes d'UUID nus (JSONField),
    jamais de FK Django vers `apps.purchase`/`apps.sales` (regle de
    couplage n°1) — resolus en reference lisible via
    `purchase.services.public.get_order_reference`/
    `sales.services.public.get_order_reference` quand necessaire."""

    STATE_PLANNED = "planned"
    STATE_BOOKED = "booked"
    STATE_PICKED_UP = "picked_up"
    STATE_IN_TRANSIT = "in_transit"
    STATE_ARRIVED_AT_PORT = "arrived_at_port"
    STATE_CUSTOMS_CLEARANCE = "customs_clearance"
    STATE_CUSTOMS_CLEARED = "customs_cleared"
    STATE_DELIVERED = "delivered"
    STATE_CLOSED = "closed"
    STATE_BLOCKED = "blocked"
    STATE_CHOICES = [
        (STATE_PLANNED, "Prevue"),
        (STATE_BOOKED, "Reservee"),
        (STATE_PICKED_UP, "Enlevee"),
        (STATE_IN_TRANSIT, "En transit"),
        (STATE_ARRIVED_AT_PORT, "Arrivee au port"),
        (STATE_CUSTOMS_CLEARANCE, "En dedouanement"),
        (STATE_CUSTOMS_CLEARED, "Dedouanee"),
        (STATE_DELIVERED, "Livree"),
        (STATE_CLOSED, "Cloturee"),
        (STATE_BLOCKED, "Bloquee"),
    ]

    # Memes valeurs que `apps.purchase.models.PurOrder.INCOTERM_CHOICES` —
    # constante Python distincte plutot qu'un import (regle de couplage
    # n°1), chaines identiques par convention documentee.
    INCOTERM_EXW = "EXW"
    INCOTERM_FOB = "FOB"
    INCOTERM_CIF = "CIF"
    INCOTERM_DAP = "DAP"
    INCOTERM_DDP = "DDP"
    INCOTERM_CHOICES = [
        (INCOTERM_EXW, "EXW — A l'usine"),
        (INCOTERM_FOB, "FOB — Franco a bord"),
        (INCOTERM_CIF, "CIF — Cout, assurance et fret"),
        (INCOTERM_DAP, "DAP — Rendu au lieu de destination"),
        (INCOTERM_DDP, "DDP — Rendu droits acquittes"),
    ]

    origin = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    carrier = models.ForeignKey(
        LogServiceProvider, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    incoterm = models.CharField(max_length=8, choices=INCOTERM_CHOICES, blank=True)
    purchase_order_ids = models.JSONField(default=list, blank=True)
    sales_order_ids = models.JSONField(default=list, blank=True)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    freight_cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # LOG-REFACT1 : montant refacture au client — distinct de
    # `freight_cost_mga` (le cout reel paye au transporteur), peut etre
    # forfaitaire plutot qu'egal au cout reel.
    freight_billed_to_customer_mga = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    state = FSMField(default=STATE_PLANNED, choices=STATE_CHOICES)
    block_reason = models.TextField(blank=True)

    class Meta:
        db_table = "log_shipment"

    def __str__(self) -> str:
        return self.reference or str(self.id)

    @transition(field=state, source=STATE_PLANNED, target=STATE_BOOKED)
    def book(self) -> None:
        pass

    @transition(field=state, source=STATE_BOOKED, target=STATE_PICKED_UP)
    def pick_up(self) -> None:
        pass

    @transition(field=state, source=STATE_PICKED_UP, target=STATE_IN_TRANSIT)
    def mark_in_transit(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_TRANSIT, target=STATE_ARRIVED_AT_PORT)
    def mark_arrived_at_port(self) -> None:
        pass

    @transition(field=state, source=STATE_ARRIVED_AT_PORT, target=STATE_CUSTOMS_CLEARANCE)
    def start_customs_clearance(self) -> None:
        pass

    @transition(field=state, source=STATE_CUSTOMS_CLEARANCE, target=STATE_CUSTOMS_CLEARED)
    def mark_customs_cleared(self) -> None:
        pass

    @transition(field=state, source=STATE_CUSTOMS_CLEARED, target=STATE_DELIVERED)
    def deliver(self) -> None:
        pass

    @transition(field=state, source=STATE_DELIVERED, target=STATE_CLOSED)
    def close(self) -> None:
        pass

    @transition(
        field=state,
        source=[
            STATE_BOOKED,
            STATE_PICKED_UP,
            STATE_IN_TRANSIT,
            STATE_ARRIVED_AT_PORT,
            STATE_CUSTOMS_CLEARANCE,
        ],
        target=STATE_BLOCKED,
    )
    def block(self) -> None:
        pass

    # Simplification assumee et documentee, meme patron que
    # `PurOrder.resolve_dispute` : quel que soit l'etat d'origine du
    # blocage, le deblocage ramene toujours a `in_transit` — un blocage
    # (retard transporteur, document manquant, litige douanier informel
    # avant ouverture du dossier officiel LOG5) se resout en general par
    # "la marchandise repart", jamais par une reprise fine de l'etape
    # exacte precedente. Pas de machine a etats "retour a l'etat
    # precedent" generique dans ce socle.
    @transition(field=state, source=STATE_BLOCKED, target=STATE_IN_TRANSIT)
    def unblock(self) -> None:
        pass


class LogShipmentLeg(BaseModel):
    MODE_ROAD = "road"
    MODE_SEA = "sea"
    MODE_AIR = "air"
    MODE_RAIL = "rail"
    MODE_CHOICES = [
        (MODE_ROAD, "Route"),
        (MODE_SEA, "Mer"),
        (MODE_AIR, "Air"),
        (MODE_RAIL, "Rail"),
    ]

    shipment = models.ForeignKey(LogShipment, on_delete=models.CASCADE, related_name="legs")
    sequence = models.PositiveIntegerField()
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default=MODE_ROAD)
    origin = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    carrier = models.ForeignKey(
        LogServiceProvider, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    departure_date = models.DateField(null=True, blank=True)
    arrival_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "log_shipment_leg"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "sequence"], name="uniq_log_shipment_leg_sequence"
            )
        ]

    def __str__(self) -> str:
        return f"{self.shipment} — etape {self.sequence}"


class LogHsCode(BaseModel):
    """LOG5 : code du systeme harmonise (SH), versionne par date d'effet —
    meme patron que `AccTax`/`AccExchangeRate` (`valid_from`/`valid_to`,
    aucune contrainte d'exclusion Postgres a ce stade, coherence laissee a
    la saisie comme pour ces deux modeles)."""

    code = models.CharField(max_length=16)
    description = models.CharField(max_length=255)
    duty_rate_pct = models.DecimalField(max_digits=6, decimal_places=3)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "log_hs_code"

    def __str__(self) -> str:
        return f"{self.code} — {self.description}"


class LogCustomsFile(BaseModel, ReferenceMixin):
    """LOG5 : dossier douanier d'un dossier d'importation. Workflow simple
    (2 transitions triviales, jamais une FSM complete) — meme discipline
    que `PurRequisition`/`AccBudget` : pas de machine a etats pour un cycle
    aussi court."""

    STATE_OPEN = "open"
    STATE_CLEARED = "cleared"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouvert"),
        (STATE_CLEARED, "Dedouane"),
        (STATE_CLOSED, "Cloture"),
    ]

    shipment = models.ForeignKey(
        LogShipment, on_delete=models.PROTECT, related_name="customs_files"
    )
    broker = models.ForeignKey(
        LogServiceProvider, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    opened_at = models.DateField()
    cleared_at = models.DateField(null=True, blank=True)
    closed_at = models.DateField(null=True, blank=True)
    # Renseigne a la cloture (RG-LOG-7) — id de l'AccLandedCostBatch cree
    # par `accounting.services.public.create_landed_cost_batch_from_source`.
    # UUID nu, jamais de FK Django (regle de couplage n°1).
    landed_cost_batch_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "log_customs_file"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class LogCustomsLine(BaseModel):
    """RG-LOG-6 : une ligne = un article dedouane, avec le calcul complet
    conserve pour tracabilite (pas seulement le resultat final) — chaque
    montant intermediaire (CAF, droits, base TVA, TVA, cout de revient) est
    stocke tel que calcule par `services/customs.py::simulate_customs_duties`
    au moment de l'ajout de la ligne, jamais recalcule silencieusement
    ensuite si le taux du `LogHsCode` change plus tard."""

    customs_file = models.ForeignKey(LogCustomsFile, on_delete=models.CASCADE, related_name="lines")
    hs_code = models.ForeignKey(LogHsCode, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=255)
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — regle
    # de couplage n°1, UUID optionnel (une ligne douaniere n'est pas
    # toujours reliee a un article du catalogue).
    variant_id = models.UUIDField(null=True, blank=True)
    qty = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    fob_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    freight_value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    insurance_value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    other_non_recoverable_taxes_mga = models.DecimalField(
        max_digits=18, decimal_places=4, default=0
    )
    transit_cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Resultats du calcul RG-LOG-6, conserves (cf. docstring de classe).
    caf_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    duty_mga = models.DecimalField(max_digits=18, decimal_places=4)
    vat_base_mga = models.DecimalField(max_digits=18, decimal_places=4)
    vat_mga = models.DecimalField(max_digits=18, decimal_places=4)
    landed_cost_mga = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "log_customs_line"

    def __str__(self) -> str:
        return f"{self.customs_file} — {self.description}"
