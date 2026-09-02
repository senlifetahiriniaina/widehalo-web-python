from apps.core.module import ModuleSpec

# "accounting" ajoute par le chantier "fiche partenaire a onglets par role"
# (PT3) : `services/accounts.py` consomme
# `apps.accounting.services.public.list_accounts`/
# `assign_partner_role_account`/`list_partner_role_accounts` — jamais un
# import de `apps.accounting.models`.
MODULE = ModuleSpec(
    name="partners", dependencies=("core", "chat", "accounting"), verbose_name="Partenaires"
)
