"""§5.11 reporting, REP5 : verifie l'enregistrement effectif des ~40
rapports deja construits par les 9 modules metier dans le registre partage.

Deux niveaux de verification :
1. **Metadata** (tous les codes) : le rapport existe, porte le bon module/
   la bonne permission/le bon renderer — detecte une faute de frappe dans
   `register_report(...)` sans avoir a construire un jeu de donnees complet
   pour chacun des ~40 rapports.
2. **Round-trip fonctionnel** (le sous-ensemble des rapports qui ne
   dependent que du tenant courant, sans FK vers un objet metier precis a
   construire — logistics/purchase/stocks/mrp/crm) : appelle reellement
   l'adaptateur enregistre et verifie qu'il ne leve pas et renvoie une
   liste. Les rapports qui exigent un objet source specifique (ex. PUR-BC
   sur un `PurOrder`, PAT-MES sur un `PatPattern`) sont deja couverts
   individuellement par les tests d'acceptance de leur propre module
   (`services/reports.py`) — reconstruire ici les memes montages n'aurait
   ajoute qu'une redondance, pas une garantie supplementaire."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

_EXPECTED_METADATA = {
    "ACC-FAC": ("accounting", "accounting.view_accmove", True),
    "ACC-BAL": ("accounting", "accounting.view_accaccount", False),
    "ACC-GL": ("accounting", "accounting.view_accmove", False),
    "ACC-JNL": ("accounting", "accounting.view_accmove", False),
    "ACC-CR": ("accounting", "accounting.view_accaccount", False),
    "ACC-CR-FCT": ("accounting", "accounting.view_accaccount", False),
    "ACC-VCP": ("accounting", "accounting.view_accaccount", False),
    "ACC-AGE-C": ("accounting", "accounting.view_accmove", False),
    "ACC-AGE-F": ("accounting", "accounting.view_accmove", False),
    "ACC-ANA": ("accounting", "accounting.view_accmove", False),
    "CRM-PIPE": ("crm", "crm.view_crmpipeline", False),
    "CRM-CONV": ("crm", "crm.view_crmpipeline", False),
    "CRM-ACT": ("crm", "crm.view_crmactivity", False),
    "CRM-PERTE": ("crm", "crm.view_crmlead", False),
    "MRP-OF": ("mrp", "mrp.view_mrporder", False),
    "MRP-COUT": ("mrp", "mrp.view_mrporder", False),
    "MRP-CRA": ("mrp", "mrp.view_mrpcra", False),
    "MRP-CRI": ("mrp", "mrp.view_mrpcri", False),
    "MRP-EFF": ("mrp", "mrp.view_mrpworkcenter", False),
    "MRP-REBUT": ("mrp", "mrp.view_mrpscrap", False),
    "MRP-CHARGE": ("mrp", "mrp.view_mrpworkshop", False),
    "PAT-MES": ("patronage", "patronage.view_patsizechart", False),
    "PAT-CONSO": ("patronage", "patronage.view_patconsumption", False),
    "PAT-MARKER": ("patronage", "patronage.view_patmarker", False),
    "PAT-VERS": ("patronage", "patronage.view_patpattern", False),
    "PUR-BC": ("purchase", "purchase.view_purorder", False),
    "PUR-RFQ": ("purchase", "purchase.view_purrfq", False),
    "PUR-COMP": ("purchase", "purchase.view_purrfq", False),
    "PUR-REC": ("purchase", "purchase.view_purorder", False),
    "PUR-ENG": ("purchase", "purchase.view_purorder", False),
    "PUR-EVAL": ("purchase", "purchase.view_purorder", False),
    "PUR-RET": ("purchase", "purchase.view_purorder", False),
    "PUR-CRI": ("purchase", "purchase.view_purcri", False),
    "STK-ETAT": ("stocks", "stocks.view_stkmove", False),
    "STK-MOUV": ("stocks", "stocks.view_stkmove", False),
    "STK-TRAC": ("stocks", "stocks.view_stkmove", False),
    "STK-INV": ("stocks", "stocks.view_stkinventory", False),
    "STK-DEF": ("stocks", "stocks.view_stkdefecttype", False),
    "STK-AGE": ("stocks", "stocks.view_stkmove", False),
    "STK-COHER": ("stocks", "stocks.view_stkmove", False),
    "STK-MES": ("stocks", "stocks.view_stkmove", False),
    "STK-VAL": ("stocks", "stocks.view_stkmove", False),
    "LOG-VEH": ("logistics", "logistics.view_logvehicle", False),
    "LOG-EXP": ("logistics", "logistics.view_logshipment", False),
    "LOG-DOUANE": ("logistics", "logistics.view_logcustomsfile", False),
    "SAL-BL": ("sales", "sales.view_salesorder", True),
    "SAL-DEVIS": ("sales", "sales.view_salesquotation", False),
    "SAL-BC": ("sales", "sales.view_salesorder", False),
    "SAL-CA": ("sales", "sales.view_salesorder", False),
    "SAL-MARGE": ("sales", "sales.view_salesorder", False),
    "SAL-RET": ("sales", "sales.view_salesorder", False),
    "SAL-OBJ": ("sales", "sales.view_salestarget", False),
    "SAL-PREV": ("sales", "sales.view_salesforecast", False),
    "PAY-BULL": ("payroll", "payroll.view_paypayslip", True),
}


@pytest.mark.parametrize("code", sorted(_EXPECTED_METADATA))
def test_report_registered_with_expected_metadata(code: str) -> None:
    module, permission, is_legal = _EXPECTED_METADATA[code]
    report = get_registered_report(code)
    assert report is not None, f"{code} n'est pas enregistre"
    assert report.module == module
    assert report.permission == permission
    assert report.is_legal_document is is_legal
    assert report.supports_pdf() or report.supports_rows()


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="RPT-MODREG", name="Reporting Module Registration Tenant")


@pytest.mark.parametrize(
    "code,params",
    [
        ("CRM-ACT", {}),
        ("CRM-PERTE", {}),
        ("MRP-CRA", {"date_from": dt.date(2026, 1, 1), "date_to": dt.date(2026, 1, 31)}),
        ("MRP-CRI", {"date_from": dt.date(2026, 1, 1), "date_to": dt.date(2026, 1, 31)}),
        ("MRP-EFF", {}),
        ("MRP-REBUT", {"date_from": dt.date(2026, 1, 1), "date_to": dt.date(2026, 1, 31)}),
        ("PUR-ENG", {}),
        ("PUR-RET", {}),
        ("PUR-CRI", {}),
        ("STK-ETAT", {}),
        ("STK-DEF", {}),
        ("STK-AGE", {}),
        ("STK-COHER", {}),
        ("STK-MES", {}),
        ("STK-VAL", {}),
        ("LOG-VEH", {}),
        ("LOG-EXP", {}),
        ("LOG-DOUANE", {}),
    ],
)
def test_tenant_only_report_round_trips_without_error(tenant, code: str, params: dict) -> None:
    report = get_registered_report(code)
    assert report is not None and report.render_rows is not None
    with use_tenant(tenant.id):
        rows = report.render_rows(params, None)
    assert isinstance(rows, list)
