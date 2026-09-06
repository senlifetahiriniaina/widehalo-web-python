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
    # "forecast" : FOR-10 (L9) — le socle doit porter la VERSION et la DATE
    # de la prevision publiee qui l'alimente, pas un chiffre anonyme
    # (`forecast.services.public.get_latest_published_forecast`), jamais
    # `apps.forecast.models`. Meme motif exact que `strategy` (budget
    # previsionnel), qui declare cette dependance depuis son propre
    # chantier : deux socles chiffres a partir de previsions dont on ne
    # peut plus dire de quelle publication elles viennent, c'est un chiffre
    # invalidable en comite.
    dependencies=("core", "sales", "accounting", "forecast"),
    verbose_name="Simulation financière",
)
