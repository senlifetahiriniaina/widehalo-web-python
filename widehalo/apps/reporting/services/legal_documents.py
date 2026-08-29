"""RPT-10 : archivage des documents legaux nommement cites par le CDC —
facture (ACC-FAC), bulletin de paie (PAY-BULL), bon de livraison (SAL-BL).
Portee assumee et disclosed (cf. plan §reporting) : les ~37 autres rapports
du catalogue restent generes a la demande (non legaux, recalcul a chaque
fois est correct et attendu pour un etat financier/operationnel) — SEULS
ces 3 documents nommement cites par le CDC beneficient de `render_and_
archive`.

**Generique par construction** : `render_and_archive` ne connait AUCUN
modele metier (`AccMove`/`PayPayslip`/`SalesOrder`) — `content_object` est
duck-type (il doit seulement porter `.tenant`/`.pk`/`.__class__`, ce que
tout `BaseModel` fournit) et `generate_fn` est une fermeture fournie par
l'APPELANT (qui, lui, vit dans `apps.accounting`/`apps.payroll`/
`apps.sales` et a donc le droit d'importer son propre modele). `reporting`
ne declare toujours de dependance que sur `core` (couplage n°1).

RPT-9 (reproductibilite) : le PDF n'est genere qu'UNE fois par objet
source — toute reimpression ulterieure sert l'octet-pour-octet deja
archive (`core.Document`, dedupliqu par SHA-256), jamais un recalcul."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.documents import store_document


def render_and_archive(
    *, content_object: Any, actor: User | None, generate_fn: Callable[[], bytes]
) -> bytes:
    """`content_object` porte l'objet source (facture/bulletin/BL) —
    resolu par l'appelant, jamais par ce module. Retourne toujours les
    memes octets pour un meme `content_object` (RPT-9)."""
    tenant = content_object.tenant
    content_type = ContentType.objects.get_for_model(content_object.__class__)
    existing = Document.objects.filter(
        tenant=tenant, content_type=content_type, object_id=str(content_object.pk)
    ).first()
    if existing is not None:
        with existing.file.open("rb") as handle:
            content: bytes = handle.read()
        return content

    data = generate_fn()
    uploaded_file = SimpleUploadedFile(
        f"{content_object.pk}.pdf", data, content_type="application/pdf"
    )
    store_document(
        tenant=tenant, uploaded_file=uploaded_file, uploaded_by=actor, content_object=content_object
    )
    return data
