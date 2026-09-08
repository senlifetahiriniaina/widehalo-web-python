from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="accounting",
    # "stocks" ajoute par le chantier de durcissement retroactif qui leve
    # le stub A17/ACC-IMP (`stocks` n'existait pas encore quand `accounting`
    # a ete construit, cf. plan) : `services.landed_costs.finalize_batch`
    # consomme desormais `apps.stocks.services.public.
    # apply_landed_cost_to_valuation` — jamais `apps.stocks.models`.
    # "catalog" et "accounting" ajoutes par le chantier RG-QUALIF :
    # `services.invoice_import` consomme `apps.catalog.services.public.
    # ensure_default_variant`/`get_variant_id_by_reference`, et reutilise
    # `apps.accounting.services.public.create_customer_invoice_from_
    # source`/`create_supplier_invoice_from_source` (deja construits pour
    # `sales`/`purchase`) plutot que de dupliquer la construction de
    # facture — un import explicite de son propre `services.public`,
    # declare ici comme tout autre gap consomme.
    # "reporting" ajoute par le chantier §5.11 (REP4) : `services.
    # reports_registration._adapter_invoice_pdf` consomme `apps.reporting.
    # services.public.render_and_archive` pour l'archivage RPT-10 de
    # ACC-FAC — jamais `apps.reporting.models`.
    # "partners" (deja declare) est desormais aussi consomme par
    # `models.py::AccPartnerRoleAccount.role` (chantier "fiche partenaire a
    # onglets par role", PT2) via `apps.partners.services.public.
    # list_role_choices()` — jamais un import de `apps.partners.models`.
    # "flows" ajoute par T4 (bloc C, e-facture) : `services.
    # einvoice_submission` et `services.einvoice_verdict` consomment
    # `apps.flows.services.public.sign_document`/
    # `describe_signing_certificate`/`list_exchanges_for_document` —
    # jamais un import de `apps.flows.models`. Le sens de la dependance
    # est celui que la docstring du hub impose : c'est le module metier
    # qui appelle le hub, et le hub ne rappelle jamais un module metier.
    #
    # La SIGNATURE traverse cette frontiere, jamais la CLEF : le cahier
    # loge le secret dans `FlwCredential` (§13.2, « table a part,
    # chiffree, jamais exportee ») et le hub rend le resultat, pas le
    # moyen.
    dependencies=(
        "core",
        "partners",
        "stocks",
        "catalog",
        "accounting",
        "reporting",
        "flows",
    ),
    verbose_name="Comptabilite",
)
