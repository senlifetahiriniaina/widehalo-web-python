from django.urls import path

from apps.payroll import views

app_name = "payroll"

urlpatterns = [
    path("", views.hr_dashboard, name="hr_dashboard"),
    path("simulation/", views.rubric_simulation, name="rubric_simulation"),
]
