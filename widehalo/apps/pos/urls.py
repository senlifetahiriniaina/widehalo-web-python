from django.urls import path

from apps.pos import views

app_name = "pos"

urlpatterns = [
    path("", views.register_list, name="index"),
    path("sale/", views.sale_screen, name="sale"),
    path("sale/open-session/", views.sale_open_session, name="sale_open_session"),
    path("sale/submit/", views.sale_submit, name="sale_submit"),
    path("sale/partner-search/", views.sale_partner_search, name="sale_partner_search"),
    path("registers/", views.register_list, name="registers"),
    path("payment-methods/", views.payment_method_list, name="payment_methods"),
    path("sessions/", views.session_list, name="sessions"),
    path("sessions/<uuid:session_id>/", views.session_detail, name="session_detail"),
    # POS-1 (L6) : le ticket imprimable. `reprint_count` documentait cet
    # ecran depuis la Phase 1 sans qu'il existe.
    path("orders/<uuid:order_id>/ticket/", views.ticket_print, name="ticket"),
    path(
        "orders/<uuid:order_id>/ticket/reprint/",
        views.ticket_reprint,
        name="ticket_reprint",
    ),
    path("sync-log/", views.sync_log_view, name="sync_log"),
]
