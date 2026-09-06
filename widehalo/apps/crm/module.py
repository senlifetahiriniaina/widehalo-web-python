from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="crm",
    # "partners" ajoute par L4 (CRM-3) : `services.leads.
    # convert_lead_to_partner` consomme `partners.services.public.
    # create_partner_with_contact_from_source` pour materialiser la societe
    # et son contact a partir des coordonnees deja portees par la piste —
    # jamais `apps.partners.models`.
    dependencies=("core", "catalog", "partners"),
    verbose_name="Relation commerciale",
)
