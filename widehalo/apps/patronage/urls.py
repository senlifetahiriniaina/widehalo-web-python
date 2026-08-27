from django.urls import path

from apps.patronage import views

app_name = "patronage"

urlpatterns = [
    path("", views.pattern_list, name="list"),
    path("new/", views.pattern_create, name="create"),
    path("<uuid:pattern_id>/", views.pattern_detail, name="detail"),
]
