from django.urls import path

from apps.whatsapp import views

app_name = "whatsapp"

urlpatterns = [
    path("", views.conversations, name="conversations"),
    path("consent/grant/", views.consent_grant, name="consent_grant"),
    path("consent/revoke/", views.consent_revoke, name="consent_revoke"),
    path("send/", views.send_message, name="send_message"),
    path("messages/retry/", views.messages_retry, name="messages_retry"),
    path("config/", views.config, name="config"),
    path("config/cost-cap/", views.cost_cap_update, name="cost_cap_update"),
    path("templates/new/", views.template_create, name="template_create"),
    path("templates/<uuid:template_id>/submit/", views.template_submit, name="template_submit"),
    path("templates/<uuid:template_id>/approve/", views.template_approve, name="template_approve"),
    path("templates/<uuid:template_id>/reject/", views.template_reject, name="template_reject"),
]
