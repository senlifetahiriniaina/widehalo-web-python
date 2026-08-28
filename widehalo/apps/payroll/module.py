from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="payroll",
    # "presence" (RG-PAY-1, chaine de calcul : jours/heures travaillees,
    # solde de conges, heures sup validees) et "accounting" (RG-PAY-8,
    # comptabilisation du lot de paie) consommees exclusivement via
    # `services.public` — jamais un import de `apps.presence.models`/
    # `apps.accounting.models`.
    dependencies=("core", "presence", "accounting"),
    verbose_name="Paie",
)
