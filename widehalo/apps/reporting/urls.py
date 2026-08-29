from django.urls import path

from apps.reporting import views

app_name = "reporting"

urlpatterns = [
    path("", views.catalog_index, name="catalog"),
    path("generate/<str:code>/", views.generate_form, name="generate_form"),
    path("generate/<str:code>/submit/", views.generate_submit, name="generate_submit"),
    path("jobs/<uuid:job_id>/", views.job_status, name="job_status"),
    path("schedules/", views.schedules_index, name="schedules"),
    path("schedules/<uuid:schedule_id>/toggle/", views.schedule_toggle, name="schedule_toggle"),
]
