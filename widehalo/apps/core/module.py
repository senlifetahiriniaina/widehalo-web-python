"""Contrat de dependances declaratives entre apps du modulith.

Chaque app metier doit exposer, dans son propre `module.py`, un objet
`MODULE = ModuleSpec(name=..., dependencies=(...))`. `tests/architecture/
test_module_boundaries.py` verifie que les dependances declarees ici
correspondent aux imports reellement observes vers `services.public`
d'autres apps.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    verbose_name: str = ""


# "accounting"/"stocks" ajoutes par le chantier RG-QUALIF :
# `apps.core.api_workflow` (endpoint generique de decision d'approbation)
# consomme `apps.accounting.services.public.decide_cash_journal_
# qualification`/`decide_invoice_import_qualification` et `apps.stocks.
# services.public.decide_stock_import_qualification` pour repercuter la
# decision generique sur le statut de la ligne d'import metier concernee
# — jamais un import de modele, uniquement leurs services.public.
# "purchase" ajoute par le Bloc F, F2 (FOR-12/FOR-13) : meme registre
# `apps.core.api_workflow._qualification_decision_hooks`, nouvelle entree
# `apps.purchase.services.public.decide_reordering_proposal` pour
# repercuter la decision generique sur une `PurReorderingProposal`.
# "crm"/"sales" ajoutes par le chantier UX6 (refonte visuelle) :
# `apps.core.views.dashboard` consomme `apps.crm.services.public.
# count_open_opportunities`/`apps.sales.services.public.
# count_orders_pending_confirmation` (+ `apps.accounting.services.public.
# count_unpaid_customer_invoices`, deja couvert par la dependance
# "accounting" ci-dessus) pour les 3 tuiles KPI du tableau de bord —
# jamais un import de modele, uniquement leurs services.public.
MODULE = ModuleSpec(
    name="core",
    dependencies=("accounting", "stocks", "purchase", "crm", "sales"),
    verbose_name="Socle",
)
