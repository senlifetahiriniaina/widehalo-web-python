from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="payroll",
    # "presence" (RG-PAY-1, chaine de calcul : jours/heures travaillees,
    # solde de conges, heures sup validees) et "accounting" (RG-PAY-8,
    # comptabilisation du lot de paie) consommees exclusivement via
    # `services.public` — jamais un import de `apps.presence.models`/
    # `apps.accounting.models`.
    # "reporting" ajoute par le chantier §5.11 (REP4) : `services.
    # reports_registration._adapter_payslip_pdf` consomme `apps.reporting.
    # services.public.render_and_archive` pour l'archivage RPT-10 de
    # PAY-BULL — jamais `apps.reporting.models`.
    dependencies=("core", "presence", "accounting", "reporting"),
    verbose_name="Paie",
)
