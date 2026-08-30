"""HD3 : tests de `services.kb` — compteurs atomiques (F()), recherche
simple, publication/depublication."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import HlpKbArticle
from apps.helpdesk.services.kb import (
    create_article,
    publish_article,
    record_article_feedback,
    record_article_view,
    search_articles,
    unpublish_article,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_author():
    tenant = Tenant.objects.create(code="HLP-KB", name="Helpdesk KB Tenant")
    with use_tenant(tenant.id):
        author = UserFactory()
        yield tenant, author


def test_create_article_defaults_to_unpublished(tenant_and_author) -> None:
    tenant, author = tenant_and_author
    with use_tenant(tenant.id):
        article = create_article(
            tenant, title="Comment reinitialiser un mot de passe ?", author=author
        )
        assert article.is_published is False
        assert article.view_count == 0


def test_publish_unpublish_round_trip(tenant_and_author) -> None:
    tenant, author = tenant_and_author
    with use_tenant(tenant.id):
        article = create_article(tenant, title="Article", author=author)
        publish_article(article)
        article.refresh_from_db()
        assert article.is_published is True

        unpublish_article(article)
        article.refresh_from_db()
        assert article.is_published is False


def test_record_article_view_increments_atomically_via_f_expression(tenant_and_author) -> None:
    """Verifie explicitement que l'increment passe par `F(...)` (pas un
    `article.view_count += 1` charge en memoire) : deux instances Python
    DIFFERENTES de la MEME ligne, chacune incrementant "a l'aveugle" sans
    relire la valeur ecrite par l'autre, doivent malgre tout aboutir a
    +2 au total — une lecture-modification-ecriture naive perdrait un des
    deux increments."""
    tenant, author = tenant_and_author
    with use_tenant(tenant.id):
        article = create_article(tenant, title="Article", author=author)
        stale_copy = HlpKbArticle.objects.get(pk=article.pk)

        record_article_view(article)
        record_article_view(stale_copy)

        article.refresh_from_db()
        assert article.view_count == 2


def test_record_article_feedback_increments_correct_counter(tenant_and_author) -> None:
    tenant, author = tenant_and_author
    with use_tenant(tenant.id):
        article = create_article(tenant, title="Article", author=author)
        record_article_feedback(article, helpful=True)
        record_article_feedback(article, helpful=True)
        record_article_feedback(article, helpful=False)

        article.refresh_from_db()
        assert article.helpful_count == 2
        assert article.not_helpful_count == 1


def test_search_articles_only_returns_published_matches(tenant_and_author) -> None:
    tenant, author = tenant_and_author
    with use_tenant(tenant.id):
        published = create_article(
            tenant, title="Rupture de stock coton", author=author, is_published=True
        )
        create_article(
            tenant, title="Rupture de stock coton (brouillon)", author=author, is_published=False
        )
        create_article(tenant, title="Autre sujet", author=author, is_published=True)

        results = list(search_articles(tenant, "coton"))

        assert results == [published]
