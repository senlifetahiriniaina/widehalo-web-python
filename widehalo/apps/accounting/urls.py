from django.urls import path

from apps.accounting import views, views_config

app_name = "accounting"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
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
]
