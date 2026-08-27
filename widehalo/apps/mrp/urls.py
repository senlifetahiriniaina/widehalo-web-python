from django.urls import path

from apps.mrp import views

app_name = "mrp"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("new/", views.order_create, name="create"),
    path("<uuid:order_id>/", views.order_detail, name="detail"),
]
