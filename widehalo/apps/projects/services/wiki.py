"""Wiki projet + rattachement de documents (PJ10). Cf. docstring de
`PrjWikiPage` (`apps/projects/models.py`) pour les decisions de
modelisation. Ce module est un simple point d'entree service au-dessus
de deux mecanismes generiques deja construits :
- hierarchie de pages : meme garde structurelle que
  `services/tasks.py::create_task` (un `parent` doit appartenir au meme
  projet) ;
- documents : passe-plat vers `core.services.documents.store_document`,
  jamais une reimplementation de la deduplication SHA-256 (cf.
  `apps/financing/services/guarantees.py::attach_legal_document` pour le
  meme patron deja applique ailleurs dans ce depot)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.projects.models import PrjProject, PrjWikiPage


def create_wiki_page(
    project: PrjProject,
    *,
    title: str,
    body: str = "",
    author: User | None = None,
    parent: PrjWikiPage | None = None,
) -> PrjWikiPage:
    if parent is not None and parent.project_id != project.id:
        raise ValidationError(
            _("Une page parente doit appartenir au même projet que la page créée.")
        )
    return PrjWikiPage.objects.create(
        tenant=project.tenant,
        project=project,
        parent=parent,
        title=title,
        body=body,
        author=author,
    )


def update_wiki_page(
    page: PrjWikiPage, *, title: str | None = None, body: str | None = None
) -> PrjWikiPage:
    update_fields = []
    if title is not None:
        page.title = title
        update_fields.append("title")
    if body is not None:
        page.body = body
        update_fields.append("body")
    if update_fields:
        page.save(update_fields=update_fields)
    return page


def list_wiki_pages(project: PrjProject) -> QuerySet[PrjWikiPage]:
    """Pages racines du projet (`parent__isnull=True`) — les enfants sont
    accessibles cote appelant/template via `page.children` (`related_name`
    explicite du champ `PrjWikiPage.parent`)."""
    return PrjWikiPage.objects.filter(project=project, parent__isnull=True)


def attach_document_to_wiki_page(
    page: PrjWikiPage, uploaded_file: UploadedFile[Any], user: User
) -> Document:
    """Passe-plat vers `store_document` — aucune duplication du mecanisme
    de deduplication SHA-256, cf. docstring de module."""
    return store_document(
        tenant=page.tenant, uploaded_file=uploaded_file, uploaded_by=user, content_object=page
    )


def attach_document_to_project(
    project: PrjProject, uploaded_file: UploadedFile[Any], user: User
) -> Document:
    """Meme passe-plat que `attach_document_to_wiki_page`, pour un
    rattachement direct au projet (ex. cahier des charges, contrat)."""
    return store_document(
        tenant=project.tenant,
        uploaded_file=uploaded_file,
        uploaded_by=user,
        content_object=project,
    )


def list_documents_for(content_object: Any) -> QuerySet[Document]:
    """Requete generique `content_type`/`object_id` deja utilisee ailleurs
    dans ce depot pour lister les documents d'une entite (cf.
    `apps/partners/views.py::partner_detail`, `apps/accounting/views.py`)
    — meme patron reutilise ici, pas de reinvention."""
    content_type = ContentType.objects.get_for_model(content_object.__class__)
    return Document.objects.filter(content_type=content_type, object_id=str(content_object.pk))
