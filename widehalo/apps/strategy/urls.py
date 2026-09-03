from django.urls import path

from apps.strategy import views

app_name = "strategy"

urlpatterns = [
    path("", views.objective_list, name="list"),
    path("new/", views.objective_create, name="create"),
    path("benchmarks/", views.benchmark_catalog, name="benchmarks"),
    path("capacity/", views.capacity_outlook, name="capacity_outlook"),
    path("pilotage/", views.pilotage, name="pilotage"),
    path("pilotage/budgets/new/", views.budget_create, name="budget_create"),
    path("pilotage/budgets/<uuid:budget_id>/lock/", views.budget_lock, name="budget_lock"),
    path("pilotage/budgets/<uuid:budget_id>/revise/", views.budget_revise, name="budget_revise"),
    path(
        "pilotage/budgets/<uuid:budget_id>/comment/",
        views.budget_variance_comment,
        name="budget_variance_comment",
    ),
    path("pilotage/initiatives/new/", views.initiative_create, name="initiative_create"),
    path("pilotage/review-packs/new/", views.review_pack_generate, name="review_pack_generate"),
    path(
        "pilotage/review-packs/<uuid:pack_id>/",
        views.review_pack_detail,
        name="review_pack_detail",
    ),
    path("pilotage/risks/new/", views.risk_create, name="risk_create"),
    path("pilotage/risks/<uuid:risk_id>/reassess/", views.risk_reassess, name="risk_reassess"),
    path("<uuid:objective_id>/activate/", views.objective_activate, name="objective_activate"),
    path("<uuid:objective_id>/", views.objective_detail, name="detail"),
]
