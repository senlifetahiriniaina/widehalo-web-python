"""Jeu de demonstration `crm` (T10, CDC §8 couche 14 — prealable a
Schemathesis) : un pipeline par defaut a 4 etapes (nouveau/qualifie/
proposition/gagne, plus une etape perdue), une equipe commerciale, un motif
de perte, 5 opportunites reparties sur ces etapes (dont une perdue avec motif
et commentaire, une avec une ligne produit ajoutee via `add_lead_line`), et 2
activites journalisees. Utilisateur de demonstration muni du role
`commercial` (acces `view/add/change` complet a `crm` + `partners`, lecture
sur `catalog` — le role qui correspond le plus directement au perimetre
fonctionnel de ce module dans la matrice RBAC)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.services.smart_defaults import apply_country_defaults
from apps.core.tenant_context import activate_tenant
from apps.crm.models import CrmLead, CrmLostReason, CrmPipeline, CrmStage, CrmTeam
from apps.crm.services.activities import log_activity
from apps.crm.services.leads import add_lead_line, create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage

DEMO_USER_EMAIL = "commercial.demo@widehalo.local"
DEMO_USER_PASSWORD = "DemoCrm#2026!"  # noqa: S105 - compte de demonstration, jamais en production


class Command(BaseCommand):
    help = (
        "Cree un jeu de demonstration coherent pour le module crm (pipeline "
        "par defaut a 4 etapes + etape perdue, une equipe, un motif de perte, "
        "5 opportunites a des etapes differentes dont une perdue et une avec "
        "ligne produit, 2 activites journalisees), utilisateur demo muni du "
        "role commercial. Idempotent pour la configuration (get_or_create) ; "
        "le jeu de 5 opportunites de demonstration n'est pas recree si ce "
        "pipeline contient deja au moins une opportunite (voir docstring)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--tenant-code", default="DEMO", help="Code du tenant a creer/reutiliser."
        )

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]
        tenant, tenant_created = Tenant.objects.get_or_create(
            code=tenant_code,
            defaults={
                "name": "Societe demonstration WideHalo",
                "country_code": "MG",
                "fiscal_regime": Tenant.FISCAL_REGIME_REAL_WITH_VAT,
            },
        )
        if tenant_created:
            apply_country_defaults(tenant, "MG")

        with activate_tenant(tenant.id):
            demo_user, user_created = User.objects.get_or_create(
                email=DEMO_USER_EMAIL,
                defaults={"first_name": "Demo", "last_name": "Commercial"},
            )
            if user_created:
                demo_user.set_password(DEMO_USER_PASSWORD)
                demo_user.save(update_fields=["password"])
            group, _ = Group.objects.get_or_create(name="commercial")
            sync_group_permissions(group, "commercial")
            demo_user.groups.add(group)

            pipeline, _ = CrmPipeline.objects.get_or_create(
                tenant=tenant,
                name="Pipeline commercial standard",
                defaults={"is_default": True},
            )
            # Etape par defaut (sequence la plus basse) : resolue automatiquement
            # par `create_lead_quick()` pour toute nouvelle opportunite, jamais
            # ciblee explicitement ci-dessous.
            CrmStage.objects.get_or_create(
                tenant=tenant,
                pipeline=pipeline,
                code="new",
                defaults={"name": "Nouveau", "sequence": 1, "probability": 10},
            )
            stage_qualified, _ = CrmStage.objects.get_or_create(
                tenant=tenant,
                pipeline=pipeline,
                code="qualified",
                defaults={"name": "Qualifie", "sequence": 2, "probability": 30},
            )
            stage_proposition, _ = CrmStage.objects.get_or_create(
                tenant=tenant,
                pipeline=pipeline,
                code="proposition",
                defaults={"name": "Proposition", "sequence": 3, "probability": 60},
            )
            stage_won, _ = CrmStage.objects.get_or_create(
                tenant=tenant,
                pipeline=pipeline,
                code="won",
                defaults={"name": "Gagne", "sequence": 4, "probability": 100, "is_won": True},
            )
            stage_lost, _ = CrmStage.objects.get_or_create(
                tenant=tenant,
                pipeline=pipeline,
                code="lost",
                defaults={
                    "name": "Perdu",
                    "sequence": 5,
                    "probability": 0,
                    "is_lost": True,
                    "requires_reason": True,
                },
            )

            team, _ = CrmTeam.objects.get_or_create(
                tenant=tenant,
                name="Equipe grands comptes",
                defaults={"leader": demo_user, "target_mga_month": Decimal("20000000")},
            )
            lost_reason, _ = CrmLostReason.objects.get_or_create(
                tenant=tenant, name="Prix trop eleve"
            )

            leads_created = 0
            if not CrmLead.objects.filter(tenant=tenant, pipeline=pipeline).exists():
                lead_new = create_lead_quick(
                    tenant=tenant,
                    name="Prospect hotellerie Ivato",
                    pipeline=pipeline,
                    contact_name="Hery Andria",
                    email="hery@hotel-ivato.example",
                    source="site_web",
                    salesperson=demo_user,
                    team=team,
                    expected_revenue_mga=Decimal("3000000"),
                )
                leads_created += 1

                lead_qualified = create_lead_quick(
                    tenant=tenant,
                    name="Uniformes ecole Ambohijatovo",
                    pipeline=pipeline,
                    contact_name="Nirina Rakoto",
                    source="salon",
                    salesperson=demo_user,
                    team=team,
                    expected_revenue_mga=Decimal("4500000"),
                )
                move_lead_to_stage(lead_qualified, stage_qualified)
                leads_created += 1

                lead_proposition = create_lead_quick(
                    tenant=tenant,
                    name="Chaine boutiques mode",
                    pipeline=pipeline,
                    contact_name="Voahangy R.",
                    source="referral",
                    salesperson=demo_user,
                    team=team,
                    expected_revenue_mga=Decimal("12500000"),
                )
                move_lead_to_stage(lead_proposition, stage_proposition)
                add_lead_line(
                    lead_proposition,
                    description="T-shirts personnalises sur-mesure",
                    qty=Decimal("500"),
                    unit_price=Decimal("18000"),
                    discount_pct=Decimal("5"),
                    is_custom=True,
                )
                leads_created += 1

                lead_won = create_lead_quick(
                    tenant=tenant,
                    name="Contrat EPI usine textile",
                    pipeline=pipeline,
                    contact_name="Tiana Rasoa",
                    source="appel_entrant",
                    salesperson=demo_user,
                    team=team,
                    expected_revenue_mga=Decimal("9000000"),
                )
                move_lead_to_stage(lead_won, stage_proposition)
                move_lead_to_stage(lead_won, stage_won)
                leads_created += 1

                lead_lost = create_lead_quick(
                    tenant=tenant,
                    name="Marche perdu - compagnie aerienne",
                    pipeline=pipeline,
                    contact_name="Fanja Andria",
                    source="salon",
                    salesperson=demo_user,
                    team=team,
                    expected_revenue_mga=Decimal("6000000"),
                )
                move_lead_to_stage(
                    lead_lost,
                    stage_lost,
                    lost_reason=lost_reason,
                    comment="Concurrent moins-disant retenu par l'appel d'offres.",
                )
                leads_created += 1

                log_activity(
                    lead_new,
                    activity_type="call",
                    subject="Appel de qualification",
                    notes="Premier contact, interesse par un devis.",
                    due_at=timezone.now(),
                    assigned_to=demo_user,
                )
                log_activity(
                    lead_proposition,
                    activity_type="meeting",
                    subject="Presentation de l'offre",
                    notes="RDV chez le client avec echantillons.",
                    due_at=timezone.now(),
                    assigned_to=demo_user,
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"crm seed OK — tenant={tenant.code} pipeline={pipeline.name} "
                f"opportunites_creees={leads_created} utilisateur_demo={DEMO_USER_EMAIL} "
                f"(role commercial)"
            )
        )
