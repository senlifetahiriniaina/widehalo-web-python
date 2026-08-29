from django.urls import path

from apps.strategy import views

app_name = "strategy"

urlpatterns = [
    path("", views.objective_list, name="list"),
    path("new/", views.objective_create, name="create"),
    path("benchmarks/", views.benchmark_catalog, name="benchmarks"),
    path("capacity/", views.capacity_outlook, name="capacity_outlook"),
    path("<uuid:objective_id>/", views.objective_detail, name="detail"),
]
