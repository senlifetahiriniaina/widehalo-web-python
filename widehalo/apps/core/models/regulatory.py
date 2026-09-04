from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class RegulatoryParameter(models.Model):
    """Parametre reglementaire versionne par date d'effet (taux, seuil,
    bareme...) — AUCUN taux/seuil/bareme ne doit jamais etre ecrit en dur
    dans le code applicatif des futurs modules (ex. bareme IRSA du futur
    module Paie). `tenant` nul = valeur globale (defaut) ; une valeur par
    tenant, si presente, prevaut (cf. services/regulatory.py::get_parameter).

    Contrainte d'exclusion Postgres (migration dediee, extension
    `btree_gist`) : deux plages de validite ne peuvent jamais se chevaucher
    pour un meme (tenant, code)."""

    # Cahier des charges WideHalo v3, Phase 1, §13.3/§17.2 (ACC-8/ACC-9) et
    # §4 DECISION ACTEE : « Aucune hypothese reglementaire ne peut etre
    # levee par defaut au motif que le developpement doit avancer : le
    # parametre reste marque non valide en base et l'ecran affiche cet
    # etat a l'utilisateur. » — d'ou STATUS_NON_VALIDE en valeur par defaut
    # (jamais VALIDE_OECFM par defaut) et le verrou de deploiement de
    # `tests/architecture/test_regulatory_deployment_gate.py`.
    STATUS_NON_VALIDE = "non_valide"
    STATUS_VALIDE_OECFM = "valide_oecfm"
    STATUS_CHOICES = [
        (STATUS_NON_VALIDE, "Non validé"),
        (STATUS_VALIDE_OECFM, "Validé OECFM"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey("core.Tenant", null=True, blank=True, on_delete=models.CASCADE)
    code = models.CharField(max_length=64)
    value = models.JSONField()
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    legal_reference = models.CharField(max_length=255, blank=True)

    statut_validation = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_NON_VALIDE
    )
    valide_par = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    valide_le = models.DateTimeField(null=True, blank=True)
    # Une correction ne modifie jamais une ligne existante (`valid_to` de
    # l'ancienne ligne est ferme, une nouvelle ligne est creee) — `version`
    # numerote cette lignee (tenant, code) dans l'ordre de creation, pour
    # affichage/audit, independamment des plages de dates elles-memes.
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "core_regulatory_parameter"

    def __str__(self) -> str:
        return f"{self.code} ({self.valid_from} → {self.valid_to or '...'})"

    def save(self, *args: object, **kwargs: object) -> None:
        # Auto-numerotation de `version` a la creation, sauf si l'appelant
        # a deja fixe explicitement une valeur differente du defaut (1) —
        # heuristique volontairement simple (cf. docstring du champ
        # ci-dessus), suffisante tant qu'aucun appelant ne cree
        # explicitement une ligne "version=1" pour une lignee qui en a deja.
        if self._state.adding and self.version == 1:
            existing_max = (
                RegulatoryParameter.objects.filter(tenant=self.tenant, code=self.code)
                .aggregate(models.Max("version"))
                .get("version__max")
            )
            if existing_max:
                self.version = existing_max + 1
        super().save(*args, **kwargs)  # type: ignore[misc]

    def mark_validated(self, by: object) -> None:
        """Validation OECFM (ACC-8) : ne modifie QUE le statut/valideur/date
        — jamais la valeur, la plage de dates ou le libelle, qui restent du
        ressort d'une nouvelle version (cf. docstring `version`).
        Journalisee comme toute autre modification (cf.
        `apps.core.audit_signals`)."""
        from django.utils import timezone

        self.statut_validation = self.STATUS_VALIDE_OECFM
        self.valide_par = by  # type: ignore[assignment]
        self.valide_le = timezone.now()
        self.save(update_fields=["statut_validation", "valide_par", "valide_le"])


class CountryDefaultsProfile(models.Model):
    """SmartDefaults par pays — preconfigure un tenant a sa creation
    (devise, TVA, fuseau, moyens de paiement...). Le plan comptable
    lui-meme (ex. PCG2005) reste une simple metadonnee informative ici :
    son chargement effectif relevera du futur module Comptabilite."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    country_code = models.CharField(max_length=2, unique=True)
    base_currency = models.CharField(max_length=3)
    default_language = models.CharField(max_length=5)
    timezone = models.CharField(max_length=64)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    chart_of_accounts_code = models.CharField(max_length=32, blank=True)
    payment_methods = models.JSONField(default=list, blank=True)
    holidays = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "core_country_defaults_profile"

    def __str__(self) -> str:
        return self.country_code
