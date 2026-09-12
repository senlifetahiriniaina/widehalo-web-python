from django.urls import path

from apps.accounting import (
    views,
    views_assets,
    views_bank,
    views_budgets,
    views_config,
    views_costing,
    views_imports,
    views_payments,
    views_reports,
    views_treasury,
)

app_name = "accounting"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
    path("quick-entry/", views.quick_entry_list, name="quick_entry_list"),
    path("quick-entry/new/", views.quick_entry_create, name="quick_entry_create"),
    path("quick-entry/<uuid:move_id>/", views.quick_entry_detail, name="quick_entry_detail"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path(
        "reports/trial-balance/",
        views_reports.trial_balance_download,
        name="report_trial_balance",
    ),
    path(
        "reports/general-ledger/",
        views_reports.general_ledger_download,
        name="report_general_ledger",
    ),
    path("reports/journal/", views_reports.journal_report_download, name="report_journal"),
    # ACC-6 (T2) : la declaration de TVA d'une periode, avec son
    # rapprochement a l'ariary pres et son etat justificatif ligne a ligne.
    path(
        "reports/vat-declaration/",
        views_reports.vat_declaration_screen,
        name="vat_declaration",
    ),
    # T5 (bloc D) — PAY-3 « visible dans un ecran dedie », et PAY-5 dont
    # le rapprochement de second niveau n'aurait, sans cette route, aucun
    # appelant. Declarees AVANT `<uuid:invoice_id>` : un prefixe litteral
    # place apres un motif attrape-tout ne serait jamais atteint.
    path(
        "payments/notifications/",
        views_payments.payment_notification_list,
        name="payment_notifications",
    ),
    path(
        "payments/notifications/<uuid:notification_id>/assign/",
        views_payments.payment_notification_assign,
        name="payment_notification_assign",
    ),
    path(
        "payments/intents/<uuid:intent_id>/reemit/",
        views_payments.payment_intent_reemit,
        name="payment_intent_reemit",
    ),
    path(
        "payments/payouts/announce/",
        views_payments.aggregator_payout_announce,
        name="payout_announce",
    ),
    path(
        "payments/payouts/<uuid:payout_id>/settle/",
        views_payments.aggregator_payout_settle,
        name="payout_settle",
    ),
    # G-2 — le patrimoine et le budget. Declarees AVANT `<uuid:invoice_id>`,
    # comme les routes de paiement : un prefixe litteral place apres un motif
    # attrape-tout ne serait jamais atteint.
    path("operations/", views.operations_index, name="operations_index"),
    path("assets/", views_assets.asset_list, name="assets"),
    path("assets/<uuid:asset_id>/", views_assets.asset_detail, name="asset_detail"),
    path("provisions/", views_assets.provision_list, name="provisions"),
    path("budgets/", views_budgets.budget_list, name="budgets"),
    path("budgets/<uuid:budget_id>/", views_budgets.budget_detail, name="budget_detail"),
    # G-3 — recouvrement, ordres de virement, echeances, monnaie electronique.
    path("dunning/", views_treasury.dunning_screen, name="dunning"),
    path("transfer-orders/", views_treasury.transfer_order_list, name="transfer_orders"),
    path(
        "transfer-orders/<uuid:order_id>/",
        views_treasury.transfer_order_detail,
        name="transfer_order_detail",
    ),
    path("tax-calendar/", views_treasury.tax_calendar_screen, name="tax_calendar"),
    path("mobile-money/", views_treasury.mobile_money_screen, name="mobile_money"),
    # G-4 — couts d'approche, DCOM.
    path("landed-costs/", views_costing.landed_cost_list, name="landed_costs"),
    path(
        "landed-costs/<uuid:batch_id>/",
        views_costing.landed_cost_detail,
        name="landed_cost_detail",
    ),
    path("dcom/", views_costing.dcom_screen, name="dcom"),
    path("<uuid:invoice_id>/", views.invoice_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/fiscal-years/", views_config.config_fiscal_years, name="config_fiscal_years"),
    path("config/periods/", views_config.config_periods, name="config_periods"),
    path("config/journals/", views_config.config_journals, name="config_journals"),
    path("config/accounts/", views_config.config_accounts, name="config_accounts"),
    path(
        "config/default-accounts/",
        views_config.config_default_accounts,
        name="config_default_accounts",
    ),
    path("config/fiscal/", views_config.config_fiscal, name="config_fiscal"),
    path("config/taxes/", views_config.config_taxes, name="config_taxes"),
    path(
        "config/payment-terms/",
        views_config.config_payment_terms,
        name="config_payment_terms",
    ),
    # G-4 — les deux referentiels sans lesquels l'analytique et les devises
    # ne fonctionnent pas : un axe non declare fait echouer la publication,
    # un taux absent fait refuser toute ecriture en devise.
    path(
        "config/analytic-plans/",
        views_config.config_analytic_plans,
        name="config_analytic_plans",
    ),
    path(
        "config/analytic-accounts/",
        views_config.config_analytic_accounts,
        name="config_analytic_accounts",
    ),
    path(
        "config/exchange-rates/",
        views_config.config_exchange_rates,
        name="config_exchange_rates",
    ),
    path("bank/", views_bank.bank_reconciliation, name="bank_reconciliation"),
    path("config/imports/", views_imports.imports_index, name="imports_index"),
    path(
        "config/imports/chart-of-accounts/",
        views_imports.imports_chart_of_accounts,
        name="imports_chart_of_accounts",
    ),
    path(
        "config/imports/chart-of-accounts/template.xlsx",
        views_imports.download_chart_of_accounts_template,
        name="imports_chart_of_accounts_template",
    ),
    path(
        "config/imports/cash-journal/",
        views_imports.imports_cash_journal,
        name="imports_cash_journal",
    ),
    path(
        "config/imports/cash-journal/template.xlsx",
        views_imports.download_cash_journal_template,
        name="imports_cash_journal_template",
    ),
    path(
        "config/imports/cash-journal/<uuid:batch_id>/",
        views_imports.imports_cash_journal_batch_detail,
        name="imports_cash_journal_batch_detail",
    ),
    path(
        "config/imports/cash-journal/rows/<uuid:row_id>/resolve/",
        views_imports.imports_cash_journal_row_resolve,
        name="imports_cash_journal_row_resolve",
    ),
    path(
        "config/imports/cash-journal/rows/<uuid:row_id>/qualify/",
        views_imports.imports_cash_journal_row_qualify,
        name="imports_cash_journal_row_qualify",
    ),
    # G-4 — l'import de factures fournisseur, meme patron que le journal de
    # caisse : depot, rapport ligne a ligne, ecart et qualification validee.
    path("config/imports/invoices/", views_imports.imports_invoices, name="imports_invoices"),
    path(
        "config/imports/invoices/template.xlsx",
        views_imports.download_invoice_template,
        name="imports_invoices_template",
    ),
    path(
        "config/imports/invoices/<uuid:batch_id>/",
        views_imports.imports_invoices_batch_detail,
        name="imports_invoices_batch_detail",
    ),
    path(
        "config/imports/invoices/rows/<uuid:row_id>/discard/",
        views_imports.imports_invoices_row_discard,
        name="imports_invoices_row_discard",
    ),
    path(
        "config/imports/invoices/rows/<uuid:row_id>/qualify/",
        views_imports.imports_invoices_row_qualify,
        name="imports_invoices_row_qualify",
    ),
]
