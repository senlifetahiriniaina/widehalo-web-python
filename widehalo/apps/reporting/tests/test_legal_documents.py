"""REP4 : `apps.reporting.services.legal_documents.render_and_archive`
(RPT-10/RPT-9) — teste generiquement (n'importe quel objet duck-type
`.tenant`/`.pk`, jamais un modele metier precis : `RptDefinition`, deja
disponible dans ce module, joue ce role ici sans violer la regle de
couplage n1). Les tests d'integration par module (ACC-FAC/PAY-BULL/SAL-BL
reels) vivent dans `apps.accounting`/`apps.payroll`/`apps.sales`."""

from __future__ import annotations

import pytest

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.reporting.models import RptDefinition
from apps.reporting.services.legal_documents import render_and_archive

pytestmark = pytest.mark.django_db


def test_render_and_archive_generates_once_then_reuses_archived_copy() -> None:
    tenant = Tenant.objects.create(code="RPT-LEGAL", name="Reporting Legal Tenant")
    user = User.objects.create_user(email="rpt-legal@example.com", password="Str0ngPassw0rd!23")
    calls = []

    def _generate() -> bytes:
        calls.append(1)
        return b"%PDF-1.4 fake content"

    with use_tenant(tenant.id):
        definition = RptDefinition.objects.create(
            tenant=tenant,
            code="RPT-LEGAL-TEST",
            module="core",
            label="Doc legal test",
            permission="core.view_tenant",
        )

        first = render_and_archive(content_object=definition, actor=user, generate_fn=_generate)
        second = render_and_archive(content_object=definition, actor=user, generate_fn=_generate)

        assert first == second == b"%PDF-1.4 fake content"
        # RPT-9 : genere une SEULE fois — la deuxieme reimpression sert la
        # copie archivee, jamais un second appel a `generate_fn`.
        assert len(calls) == 1
        assert Document.objects.filter(object_id=str(definition.id)).count() == 1
