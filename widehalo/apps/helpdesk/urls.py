from django.urls import path

from apps.helpdesk import views

app_name = "helpdesk"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("new/", views.ticket_create, name="create"),
    path("<uuid:ticket_id>/", views.ticket_detail, name="detail"),
]
