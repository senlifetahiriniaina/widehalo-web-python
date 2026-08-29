from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.projects.services.projects import create_project
from apps.projects.services.wiki import (
    attach_document_to_project,
    attach_document_to_wiki_page,
    create_wiki_page,
    list_documents_for,
    list_wiki_pages,
    update_wiki_page,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def wiki_ctx():
    tenant = Tenant.objects.create(code="PRJ-WIKI-T1", name="Projects Wiki Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet avec wiki")
        user = User.objects.create_user(
            email="wiki-author@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user


def test_create_wiki_page_defaults(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        page = create_wiki_page(project, title="Page d'accueil", body="Bonjour", author=user)
        assert page.project_id == project.id
        assert page.parent_id is None
        assert page.title == "Page d'accueil"
        assert page.body == "Bonjour"
        assert page.author_id == user.id


def test_create_wiki_page_with_valid_parent_in_same_project(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        root = create_wiki_page(project, title="Racine", author=user)
        child = create_wiki_page(project, title="Enfant", author=user, parent=root)
        assert child.parent_id == root.id
        assert list(root.children.all()) == [child]


def test_create_wiki_page_rejects_parent_from_another_project(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Autre projet")
        other_root = create_wiki_page(other_project, title="Racine autre projet", author=user)
        with pytest.raises(ValidationError):
            create_wiki_page(project, title="Enfant errone", author=user, parent=other_root)


def test_list_wiki_pages_returns_only_roots_of_this_project(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Autre projet")
        root = create_wiki_page(project, title="Racine", author=user)
        create_wiki_page(project, title="Enfant", author=user, parent=root)
        create_wiki_page(other_project, title="Racine autre projet", author=user)

        roots = list_wiki_pages(project)
        assert list(roots) == [root]


def test_update_wiki_page_partial(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        page = create_wiki_page(project, title="Titre initial", body="Corps initial", author=user)
        update_wiki_page(page, title="Titre modifie")
        page.refresh_from_db()
        assert page.title == "Titre modifie"
        assert page.body == "Corps initial"

        update_wiki_page(page, body="Nouveau corps")
        page.refresh_from_db()
        assert page.title == "Titre modifie"
        assert page.body == "Nouveau corps"


def test_attach_document_to_wiki_page_and_list(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        page = create_wiki_page(project, title="Page avec doc", author=user)
        uploaded = SimpleUploadedFile("note.txt", b"contenu du document", content_type="text/plain")
        document = attach_document_to_wiki_page(page, uploaded, user)
        assert document.content_object == page

        documents = list_documents_for(page)
        assert list(documents) == [document]


def test_attach_document_to_project_and_list(wiki_ctx) -> None:
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        uploaded = SimpleUploadedFile(
            "cahier.txt", b"cahier des charges", content_type="text/plain"
        )
        document = attach_document_to_project(project, uploaded, user)
        assert document.content_object == project

        documents = list_documents_for(project)
        assert list(documents) == [document]


def test_attach_same_document_twice_deduplicates_by_sha256(wiki_ctx) -> None:
    """Comportement deja garanti par `store_document` (SHA-256) — ce test
    verifie juste que `projects` ne le contourne pas (deux rattachements
    d'un MEME contenu, sur des entites DIFFERENTES du meme tenant, ne
    creent qu'un seul enregistrement `Document`, `reference_count`
    incremente)."""
    tenant, project, user = wiki_ctx
    with use_tenant(tenant.id):
        page = create_wiki_page(project, title="Page avec doc", author=user)
        content = b"contenu identique"
        first = attach_document_to_wiki_page(
            page, SimpleUploadedFile("v1.txt", content, content_type="text/plain"), user
        )
        second = attach_document_to_project(
            project, SimpleUploadedFile("v2.txt", content, content_type="text/plain"), user
        )
        assert first.id == second.id
        second.refresh_from_db()
        assert second.reference_count == 2
