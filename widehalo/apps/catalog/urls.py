from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("templates/", views.template_list, name="template_list"),
]
