"""API CRUD minimale des gabarits de controle qualite et des inspections
(QLT1-2). Contrairement a `apps.core.api_risk`, aucun scoping "owner" ici
(cf. commentaire de `rbac_policy._QLT_FULL_ROLES`) : toute permission
`core.view_qlt*` donne acces a l'ensemble des donnees du tenant (RLS deja
force par `BaseModel`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.quality import QltChecklistTemplate, QltInspection
from apps.core.services.permissions import require_permission
from apps.core.services.quality import create_checklist_template, create_inspection

router = Router(tags=["quality"])


class ChecklistTemplateIn(Schema):
    name: str
    sector_code: str = ""
    items: list[dict[str, Any]] = []


class InspectionIn(Schema):
    template_id: str
    results: list[dict[str, Any]]
    inspected_at: datetime
    content_type_id: int | None = None
    object_id: str = ""


def _serialize_template(template: QltChecklistTemplate) -> dict:
    return {
        "id": str(template.id),
        "name": template.name,
        "sector_code": template.sector_code,
        "items": template.items,
    }


def _serialize_inspection(inspection: QltInspection) -> dict:
    return {
        "id": str(inspection.id),
        "template_id": str(inspection.template_id),
        "results": inspection.results,
        "passed": inspection.passed,
        "inspector_id": str(inspection.inspector_id),
        "inspected_at": inspection.inspected_at.isoformat(),
        "content_type_id": inspection.content_type_id,
        "object_id": inspection.object_id,
    }


@router.get("/quality/templates")
@require_permission("core.view_qltchecklisttemplate")
def list_templates(request):
    return {"results": [_serialize_template(t) for t in QltChecklistTemplate.objects.all()]}


@router.get("/quality/templates/{template_id}")
@require_permission("core.view_qltchecklisttemplate")
def get_template(request, template_id: str):
    template = get_object_or_404(QltChecklistTemplate, id=template_id)
    return _serialize_template(template)


@router.post("/quality/templates")
@require_permission("core.add_qltchecklisttemplate")
def create_template_endpoint(request, payload: ChecklistTemplateIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    template = create_checklist_template(
        tenant=tenant,
        name=payload.name,
        created_by=request.auth,
        sector_code=payload.sector_code,
        items=payload.items,
    )
    return _serialize_template(template)


@router.get("/quality/inspections")
@require_permission("core.view_qltinspection")
def list_inspections(request, content_type_id: int | None = None, object_id: str = ""):
    """Liste les inspections, filtrees par entite rattachee si
    `content_type_id`/`object_id` sont fournis tous les deux (meme idiome
    que `apps.core.services.quality.list_inspections_for`, sans y passer
    une instance concrete puisque l'API ne recoit qu'un couple
    type/identifiant)."""
    queryset = QltInspection.objects.all()
    if content_type_id is not None and object_id:
        queryset = queryset.filter(content_type_id=content_type_id, object_id=object_id)
    return {"results": [_serialize_inspection(i) for i in queryset.order_by("-inspected_at")]}


@router.get("/quality/inspections/{inspection_id}")
@require_permission("core.view_qltinspection")
def get_inspection(request, inspection_id: str):
    inspection = get_object_or_404(QltInspection, id=inspection_id)
    return _serialize_inspection(inspection)


@router.post("/quality/inspections")
@require_permission("core.add_qltinspection")
def create_inspection_endpoint(request, payload: InspectionIn):
    from django.contrib.contenttypes.models import ContentType

    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    template = get_object_or_404(QltChecklistTemplate, id=payload.template_id)
    content_object = None
    if payload.content_type_id is not None and payload.object_id:
        content_type = get_object_or_404(ContentType, id=payload.content_type_id)
        model_class = content_type.model_class()
        if model_class is not None:
            content_object = model_class.objects.filter(pk=payload.object_id).first()
    inspection = create_inspection(
        tenant=tenant,
        template=template,
        inspector=request.auth,
        results=payload.results,
        inspected_at=payload.inspected_at,
        content_object=content_object,
    )
    return _serialize_inspection(inspection)
