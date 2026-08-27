from django.urls import path

from apps.catalog import views, views_config

app_name = "catalog"

urlpatterns = [
    path("templates/", views.template_list, name="template_list"),
    path("templates/<uuid:template_id>/", views.template_detail, name="template_detail"),
    path("textile-converter/", views.textile_converter, name="textile_converter"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/categories/", views_config.config_categories, name="config_categories"),
    path("config/attributes/", views_config.config_attributes, name="config_attributes"),
    path("config/units/", views_config.config_uom, name="config_uom"),
    path("config/price-lists/", views_config.config_price_lists, name="config_price_lists"),
    path(
        "config/price-lists/<uuid:price_list_id>/",
        views_config.price_list_detail,
        name="price_list_detail",
    ),
    path("config/packaging/", views_config.config_packaging, name="config_packaging"),
    path("config/standards/", views_config.config_standards, name="config_standards"),
    path(
        "config/certifications/",
        views_config.config_certifications,
        name="config_certifications",
    ),
]
