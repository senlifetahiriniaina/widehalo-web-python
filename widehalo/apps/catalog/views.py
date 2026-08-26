from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse

from apps.catalog.models import ProductTemplate
from apps.core.views.smart_table import Column, smart_table_response

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="base_price_mga", label="Prix catalogue (MGA)", searchable=False),
]


@login_required
def template_list(request: HttpRequest) -> HttpResponse:
    queryset = ProductTemplate.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="catalog.templates",
        columns=COLUMNS,
        queryset=queryset,
        page_template="catalog/templates_list.html",
    )
