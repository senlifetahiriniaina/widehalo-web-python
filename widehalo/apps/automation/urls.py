from django.urls import path

from apps.automation import views

app_name = "automation"

urlpatterns = [
    path("", views.flow_list, name="list"),
    path("new/", views.flow_create, name="create"),
    path("<uuid:flow_id>/builder/", views.flow_builder, name="builder"),
    path("<uuid:flow_id>/runs/", views.run_history, name="run_history"),
    path("runs/<uuid:run_id>/", views.run_detail, name="run_detail"),
]
