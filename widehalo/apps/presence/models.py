"""Modeles du module `presence` (§5.9 du CDC). Budget modeles serre a la
cloture du module `logistics` (170/180) : conception volontairement econome
en nombre de tables plutot que fidele table-par-table a la liste
`5.9.2` du CDC — chaque ecart est documente a l'endroit precis :

- `prs_public_holiday` (CDC) n'est PAS un modele dedie : les jours feries
  sont des `core.RegulatoryParameter` verses avec `code=
  "presence.public_holiday"` (cf. `services/calendar.py`) — reutilisation
  directe du mecanisme deja construit au Lot 1 etape 10 pour tout
  bareme/seuil versionne, exactement la nature d'un jour ferie
  (`is_worked`/`pay_rate_pct` par date).
- `prs_absence_approval` (CDC) n'est PAS un modele dedie : RG-PRS-5
  (circuit a niveaux parametrables) et WF-6 (delegation) reutilisent tels
  quels `core.ApprovalRule`/`ApprovalRequest`/`ApprovalDelegation` (Lot 1
  etape 8), exactement le patron deja applique par `accounting`/`sales`/
  `purchase` (cf. `services/absences.py::ensure_default_approval_rules`).
- `prs_skill` (catalogue de competences, CDC PRS-COMP1) est fusionne dans
  `PrsEmployeeSkill.skill_name` (texte libre au lieu d'une table de
  reference separee) — simplification disclosed, un vrai catalogue
  normalise viendra si le besoin de reporting inter-competences se
  confirme.
- `prs_employee_document` (PRS-DOC1) et le suivi de checklist d'onboarding
  (PRS-ONB1) sont fusionnes dans UN seul modele `PrsEmployeeTask`
  (`kind="document"` / `kind="onboarding"`) — les deux sont structurellement
  la meme forme (employe + libelle + date cible + responsable + etat),
  disclosed.

Couplage inter-app : `workshop`/`contract_current` sont des UUID simples
(jamais de FK Django vers `mrp`/le futur module Paie, cf. regle de
couplage n1). `photo` (CDC) n'est pas un champ dedie : reutiliser le
`core.Document` polymorphe existant (content_type/object_id sur
`PrsEmployee`) plutot qu'un `ImageField` redondant — disclosed, aucun
ecran de ce chantier n'exploite encore l'upload de photo (dette assumee,
pas un besoin exprime explicitement au CDC au-dela du champ lui-meme)."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, transition

from apps.core.db.fields import EncryptedCharField
from apps.core.models.base import BaseModel, ReferenceMixin


class PrsDepartment(BaseModel):
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    manager = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "prs_department"

    def __str__(self) -> str:
        return self.name


class PrsWorkCalendar(BaseModel):
    name = models.CharField(max_length=150)
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("40"))
    # {"mon": [["08:00","12:00"],["14:00","17:00"]], "tue": [...], ...}
    days = models.JSONField(default=dict, blank=True)
    tolerance_min = models.PositiveSmallIntegerField(default=5)
    # {"h_sup_30": {"multiplier": "1.30"}, "h_sup_50": {...}, "nuit": {...}, ...}
    overtime_rules = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "prs_work_calendar"

    def __str__(self) -> str:
        return self.name


class PrsEmployee(BaseModel, ReferenceMixin):
    """`reference` (ReferenceMixin, sequence PRS-<annee>-NNNN) porte le
    "code" matricule du CDC — pas de colonne dupliquee."""

    GENDER_M = "m"
    GENDER_F = "f"
    GENDER_OTHER = "other"
    GENDER_CHOICES = [
        (GENDER_M, _("Masculin")),
        (GENDER_F, _("Féminin")),
        (GENDER_OTHER, _("Autre")),
    ]

    user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    # RG-PRS-9 : donnee sensible, chiffree au repos (cf. apps/core/db/fields.py).
    cin = EncryptedCharField(max_length=64, blank=True)
    cnaps_number = models.CharField(max_length=32, blank=True)
    ostie_number = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    emergency_contact = models.CharField(max_length=255, blank=True)
    hire_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    department = models.ForeignKey(
        PrsDepartment, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees"
    )
    job_title = models.CharField(max_length=150, blank=True)
    manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )
    # Reference simple (jamais de FK) vers `mrp.MrpWorkshop` / le futur
    # contrat du module Paie — cf. docstring de module.
    workshop_id = models.UUIDField(null=True, blank=True)
    work_calendar = models.ForeignKey(
        PrsWorkCalendar, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees"
    )
    contract_current_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "prs_employee"

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or (self.reference or str(self.id))

    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )
        if self.end_date and self.hire_date and self.end_date < self.hire_date:
            raise ValidationError(_("La date de fin ne peut pas précéder la date d'embauche."))


class PrsAttendance(BaseModel):
    """RG-PRS-1/2/3/4 : un pointage. La geolocalisation precise
    (`latitude`/`longitude`) est purgee au-dela de 30 jours (RG-PRS-2) —
    seul `within_perimeter` survit, cf. `services/retention.py::
    purge_expired_geolocation`."""

    MODE_KIOSK = "kiosque"
    MODE_WEB = "web"
    MODE_MOBILE = "mobile"
    MODE_MANUAL = "manuel"
    # [V2, differe] badge/biometrie (RG-PRS-1) — non implementes, presents
    # dans les choices pour ne pas re-migrer plus tard, jamais produits par
    # ce lot.
    MODE_BADGE = "badge"
    MODE_BIOMETRIC = "biometrie"
    MODE_CHOICES = [
        (MODE_KIOSK, _("Kiosque")),
        (MODE_WEB, _("Web")),
        (MODE_MOBILE, _("Mobile")),
        (MODE_MANUAL, _("Manuel")),
        (MODE_BADGE, _("Badge")),
        (MODE_BIOMETRIC, _("Biométrie")),
    ]

    LOCATION_SITE = "site"
    LOCATION_REMOTE = "distance"
    LOCATION_CLIENT = "client"
    LOCATION_WORKSHOP = "atelier"
    LOCATION_MISSION = "mission"
    LOCATION_CHOICES = [
        (LOCATION_SITE, _("Site")),
        (LOCATION_REMOTE, _("Télétravail")),
        (LOCATION_CLIENT, _("Client")),
        (LOCATION_WORKSHOP, _("Atelier")),
        (LOCATION_MISSION, _("Mission")),
    ]

    STATE_DRAFT = "draft"
    STATE_VALIDATED = "validated"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_VALIDATED, _("Validé")),
    ]

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="attendances")
    date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    location = models.CharField(max_length=16, choices=LOCATION_CHOICES, default=LOCATION_SITE)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_captured_at = models.DateTimeField(null=True, blank=True)
    # RG-PRS-2 : seul champ de geolocalisation conserve au-dela de 30j.
    # Null tant qu'aucun geofencing n'est configure/exerce pour ce pointage.
    within_perimeter = models.BooleanField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    device = models.CharField(max_length=150, blank=True)
    worked_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    validated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    comment = models.TextField(blank=True)

    class Meta:
        db_table = "prs_attendance"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date", "mode"], name="uniq_prs_attendance_employee_date_mode"
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass


class PrsAbsenceType(BaseModel):
    CATEGORY_PAID_LEAVE = "conge_paye"
    CATEGORY_UNPAID_LEAVE = "conge_sans_solde"
    CATEGORY_SICK = "maladie"
    CATEGORY_MATERNITY = "maternite"
    CATEGORY_PATERNITY = "paternite"
    CATEGORY_PERMISSION = "permission"
    CATEGORY_TRAINING = "formation"
    CATEGORY_UNJUSTIFIED = "injustifie"
    CATEGORY_MISSION = "mission"
    CATEGORY_RECOVERY = "recuperation"
    CATEGORY_CHOICES = [
        (CATEGORY_PAID_LEAVE, _("Congé payé")),
        (CATEGORY_UNPAID_LEAVE, _("Congé sans solde")),
        (CATEGORY_SICK, _("Maladie")),
        (CATEGORY_MATERNITY, _("Maternité")),
        (CATEGORY_PATERNITY, _("Paternité")),
        (CATEGORY_PERMISSION, _("Permission")),
        (CATEGORY_TRAINING, _("Formation")),
        (CATEGORY_UNJUSTIFIED, _("Injustifié")),
        (CATEGORY_MISSION, _("Mission")),
        (CATEGORY_RECOVERY, _("Récupération")),
    ]

    # Categories dont le motif est de nature medicale (RG-PRS-9 :
    # confidentialite renforcee sur `PrsAbsence.reason`).
    MEDICAL_CATEGORIES = {CATEGORY_SICK, CATEGORY_MATERNITY, CATEGORY_PATERNITY}

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    is_paid = models.BooleanField(default=True)
    pay_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("100"))
    requires_justification = models.BooleanField(default=False)
    max_days_year = models.PositiveSmallIntegerField(null=True, blank=True)
    deducts_from_balance = models.BooleanField(default=True)
    approval_levels = models.PositiveSmallIntegerField(default=1)
    advance_notice_days = models.PositiveSmallIntegerField(default=0)
    # RG-PRS-6 : delai (jours) au-dela duquel une absence de cette
    # categorie, requerant un justificatif jamais fourni, bascule
    # automatiquement en "injustifie".
    justification_deadline_days = models.PositiveSmallIntegerField(default=2)

    class Meta:
        db_table = "prs_absence_type"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_prs_absence_type_code")
        ]

    def __str__(self) -> str:
        return self.name


class PrsAbsence(BaseModel, ReferenceMixin):
    """Workflow §5.9.4 : brouillon -> soumise -> approuvee niveau 1 ->
    approuvee niveau 2 -> validee -> en cours -> terminee, avec
    refus/annulation. Le nombre de niveaux d'approbation effectivement
    exerces vient de `PrsAbsenceType.approval_levels` (RG-PRS-5) ; le
    circuit lui-meme est porte par `core.ApprovalRule`/`ApprovalRequest`
    (jamais un modele `prs_absence_approval` dedie, cf. docstring de
    module)."""

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_APPROVED_L1 = "approved_l1"
    STATE_APPROVED_L2 = "approved_l2"
    STATE_VALIDATED = "validated"
    STATE_IN_PROGRESS = "in_progress"
    STATE_DONE = "done"
    STATE_REJECTED = "rejected"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_SUBMITTED, _("Soumise")),
        (STATE_APPROVED_L1, _("Approuvée niveau 1")),
        (STATE_APPROVED_L2, _("Approuvée niveau 2")),
        (STATE_VALIDATED, _("Validée")),
        (STATE_IN_PROGRESS, _("En cours")),
        (STATE_DONE, _("Terminée")),
        (STATE_REJECTED, _("Refusée")),
        (STATE_CANCELLED, _("Annulée")),
    ]

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="absences")
    type = models.ForeignKey(PrsAbsenceType, on_delete=models.PROTECT, related_name="absences")
    date_from = models.DateField()
    date_to = models.DateField()
    half_day_start = models.BooleanField(default=False)
    half_day_end = models.BooleanField(default=False)
    days_count = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    # RG-PRS-9 : motif potentiellement medical — chiffre au repos des que
    # `type.category` appartient a `PrsAbsenceType.MEDICAL_CATEGORIES`
    # (impose par `services/absences.py`, jamais laisse au choix de
    # l'appelant).
    reason = EncryptedCharField(max_length=500, blank=True)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    requested_at = models.DateTimeField(null=True, blank=True)
    replacement_employee = models.ForeignKey(
        PrsEmployee, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # RG-PRS-6 : justificatif(s) — reutilise `core.Document` polymorphe
    # (content_type/object_id sur cette instance), jamais une FK dediee.
    justification_provided = models.BooleanField(default=False)

    class Meta:
        db_table = "prs_absence"

    def __str__(self) -> str:
        return self.reference or f"Absence {self.employee} {self.date_from}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_SUBMITTED)
    def submit(self) -> None:
        pass

    @transition(field=state, source=STATE_SUBMITTED, target=STATE_APPROVED_L1)
    def approve_level1(self) -> None:
        pass

    @transition(field=state, source=STATE_APPROVED_L1, target=STATE_APPROVED_L2)
    def approve_level2(self) -> None:
        pass

    @transition(field=state, source=[STATE_APPROVED_L1, STATE_APPROVED_L2], target=STATE_VALIDATED)
    def validate(self) -> None:
        pass

    @transition(field=state, source=STATE_VALIDATED, target=STATE_IN_PROGRESS)
    def start(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PROGRESS, target=STATE_DONE)
    def finish(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_SUBMITTED, STATE_APPROVED_L1, STATE_APPROVED_L2],
        target=STATE_REJECTED,
    )
    def reject(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_DRAFT, STATE_SUBMITTED, STATE_APPROVED_L1, STATE_APPROVED_L2],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass


class PrsLeaveBalance(BaseModel):
    """RG-PRS-7 : solde de conges par employe/annee/type, avec historique
    de mouvements (`movements`, JSONField — liste d'entrees
    `{date, kind, days, comment}`, plutot qu'un modele de grand-livre
    dedie : autre economie de modele imposee par le budget serre, disclosed)."""

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="balances")
    year = models.PositiveSmallIntegerField()
    type = models.ForeignKey(PrsAbsenceType, on_delete=models.PROTECT, related_name="+")
    acquired_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    taken_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    pending_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    carried_over_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    expiry_date = models.DateField(null=True, blank=True)
    movements = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "prs_leave_balance"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "type"],
                name="uniq_prs_leave_balance_employee_year_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.year} {self.type_id}"

    @property
    def remaining_days(self) -> Decimal:
        return self.acquired_days + self.carried_over_days - self.taken_days - self.pending_days


class PrsOvertime(BaseModel):
    RATE_H_SUP_30 = "h_sup_30"
    RATE_H_SUP_50 = "h_sup_50"
    RATE_NIGHT = "nuit"
    RATE_SUNDAY = "dimanche"
    RATE_HOLIDAY = "ferie"
    RATE_CHOICES = [
        (RATE_H_SUP_30, _("Heures sup. 30%")),
        (RATE_H_SUP_50, _("Heures sup. 50%")),
        (RATE_NIGHT, _("Nuit")),
        (RATE_SUNDAY, _("Dimanche")),
        (RATE_HOLIDAY, _("Jour férié")),
    ]

    STATE_DRAFT = "draft"
    STATE_VALIDATED = "validated"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_VALIDATED, _("Validé")),
    ]

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="overtimes")
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    rate_category = models.CharField(max_length=16, choices=RATE_CHOICES)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    validated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Reference libre vers la future periode de paie (module Paie, pas
    # encore construit) — texte plutot qu'une FK vers un modele qui
    # n'existe pas encore.
    payroll_period = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "prs_overtime"

    def __str__(self) -> str:
        return f"{self.employee} {self.date} {self.rate_category}"

    @transition(field=state, source=STATE_DRAFT, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass


class PrsEmployeeSkill(BaseModel):
    """PRS-COMP1 (enrichissement "Adopter") : matrice de competences.
    `skill_name` est du texte libre (pas de `prs_skill` catalogue separe,
    cf. docstring de module — economie de modele imposee par le budget)."""

    LEVEL_NOVICE = "novice"
    LEVEL_INTERMEDIATE = "intermediaire"
    LEVEL_CONFIRMED = "confirme"
    LEVEL_EXPERT = "expert"
    LEVEL_CHOICES = [
        (LEVEL_NOVICE, _("Novice")),
        (LEVEL_INTERMEDIATE, _("Intermédiaire")),
        (LEVEL_CONFIRMED, _("Confirmé")),
        (LEVEL_EXPERT, _("Expert")),
    ]

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="skills")
    skill_name = models.CharField(max_length=150)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_NOVICE)
    evaluated_at = models.DateField(null=True, blank=True)
    evaluated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "prs_employee_skill"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "skill_name"], name="uniq_prs_employee_skill_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee} — {self.skill_name} ({self.level})"


class PrsEmployeeTask(BaseModel):
    """PRS-DOC1 (suivi d'expiration de documents) + PRS-ONB1 (checklist
    d'onboarding) fusionnes — meme forme structurelle, cf. docstring de
    module. `kind="document"` : `target_date` porte l'echeance
    (`expiry_date`), `alert_days_before`/`notified_at` pilotent l'alerte
    (meme patron que `logistics.LogVehicleDocument`, RG-LOG-1).
    `kind="onboarding"` : `target_date` porte l'echeance de la tache,
    `completed_at` marque son execution — `alert_days_before`/
    `notified_at` restent inutilises (simplification disclosed, pas de
    reminder d'onboarding en V1)."""

    KIND_DOCUMENT = "document"
    KIND_ONBOARDING = "onboarding"
    KIND_CHOICES = [
        (KIND_DOCUMENT, _("Document")),
        (KIND_ONBOARDING, _("Intégration")),
    ]

    employee = models.ForeignKey(PrsEmployee, on_delete=models.CASCADE, related_name="tasks")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    code = models.CharField(max_length=64, blank=True)
    label = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    alert_days_before = models.PositiveSmallIntegerField(default=30)
    notified_at = models.DateTimeField(null=True, blank=True)
    responsible = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "prs_employee_task"

    def __str__(self) -> str:
        return f"{self.employee} — {self.label}"
