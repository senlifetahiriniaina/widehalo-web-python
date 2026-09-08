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
    *,
    content_object: Any,
    actor: User | None,
    generate_fn: Callable[[], bytes],
    variant: str = "",
) -> bytes:
    """`content_object` porte l'objet source (facture/bulletin/BL) —
    resolu par l'appelant, jamais par ce module. Retourne toujours les
    memes octets pour un meme `content_object` (RPT-9).

    **`variant` (T4, bloc C).** RPT-9 et le critere EFA-4 se contredisent
    tant qu'une piece n'a qu'un seul document. RPT-9 : le PDF n'est genere
    qu'UNE fois et toute reimpression sert l'octet-pour-octet archive.
    EFA-4 : « l'identifiant attribue et le marquage verifiable sont
    reportes sur la representation lisible du document » — donc APRES le
    verdict, qui arrive apres l'archivage.

    Les deux ne peuvent pas etre vrais du meme fichier, et la lecture qui
    les concilie est celle que fait un vrai dispositif fiscal : DEUX
    documents. Celui qui est soumis, fige et jamais retouche ; et celui
    qu'on remet au client, produit une fois le verdict connu et portant le
    marquage. RPT-9 est alors tenu PAR VARIANTE — chacune n'est generee
    qu'une fois — et EFA-4 est satisfait sans qu'aucun octet archive ne
    soit reecrit.

    `variant` vide conserve exactement le comportement anterieur : un seul
    document par objet, meme nom de fichier, meme recherche. Aucun
    appelant existant n'a a changer."""
    tenant = content_object.tenant
    content_type = ContentType.objects.get_for_model(content_object.__class__)
    nom = f"{content_object.pk}.pdf" if not variant else f"{content_object.pk}-{variant}.pdf"
    # La variante entre dans la RECHERCHE autant que dans le nom : sans
    # cela, la seconde variante retrouverait le document de la premiere et
    # rendrait ses octets — un marquage fiscal servi a la place de la
    # facture soumise, ou l'inverse, sans que rien ne le signale.
    existing = Document.objects.filter(
        tenant=tenant,
        content_type=content_type,
        object_id=str(content_object.pk),
        original_name=nom,
    ).first()
    if existing is not None:
        with existing.file.open("rb") as handle:
            content: bytes = handle.read()
        return content

    data = generate_fn()
    uploaded_file = SimpleUploadedFile(nom, data, content_type="application/pdf")
    store_document(
        tenant=tenant, uploaded_file=uploaded_file, uploaded_by=actor, content_object=content_object
    )
    return data
