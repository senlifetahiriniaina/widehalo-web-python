from django.urls import path

from apps.accounting import views, views_config, views_imports, views_reports

app_name = "accounting"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
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
    path("<uuid:invoice_id>/", views.invoice_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/fiscal-years/", views_config.config_fiscal_years, name="config_fiscal_years"),
    path("config/periods/", views_config.config_periods, name="config_periods"),
    path("config/journals/", views_config.config_journals, name="config_journals"),
    path("config/accounts/", views_config.config_accounts, name="config_accounts"),
    path("config/taxes/", views_config.config_taxes, name="config_taxes"),
    path(
        "config/payment-terms/",
        views_config.config_payment_terms,
        name="config_payment_terms",
    ),
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
]
