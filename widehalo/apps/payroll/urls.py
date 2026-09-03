from django.urls import path

from apps.payroll import views

app_name = "payroll"

urlpatterns = [
    path("", views.my_payslips, name="my_payslips"),
    path("dashboard/", views.hr_dashboard, name="hr_dashboard"),
    path("<uuid:payslip_id>/", views.payslip_detail, name="payslip_detail"),
    path("<uuid:payslip_id>/pdf/", views.payslip_download, name="payslip_download"),
]
