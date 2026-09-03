from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="simulation",
    # "sales" : chiffre d'affaires/marge de reference du socle
    # (`sales.services.public` — nouveaux gaps `get_revenue_summary`/
    # `get_margin_summary`), jamais `apps.sales.models`.
    # "accounting" : postes du compte de resultat (`get_income_statement_
    # summary`), previsionnel de tresorerie et lignes ouvertes recevables/
    # payables (`get_treasury_forecast_summary`/`get_open_settlement_
    # items`), jamais `apps.accounting.models`.
    # PAS de dependance vers "pos" : le socle agrege le chiffre d'affaires
    # via `sales` uniquement (cahier §13.6, "alimentee par l'encours client
    # reel" — le CA POS retombe deja en comptabilite a la cloture de
    # session via `accounting`, deja compte dans le compte de resultat, pas
    # besoin d'un second chemin direct vers `pos`).
    dependencies=("core", "sales", "accounting"),
    verbose_name="Simulation financière",
)
