"""Services metier de la base de connaissances interne (HD3, cf. plan
« prochaine etape » de la section HD2 TERMINÉ) : creation/publication
d'articles, compteurs agreges (vues, feedback), recherche simple.

**Compteurs atomiques** : `record_article_view`/`record_article_feedback`
incrementent via `F(...)` (jamais un `article.view_count += 1` charge en
memoire puis sauve — une lecture-modification-ecriture perdrait des
increments sous acces concurrents). `refresh_from_db()` est appele apres
chaque `update()` pour renvoyer une instance a jour a l'appelant (l'API/
l'ecran affichent la valeur fraiche, pas la valeur potentiellement perimee
capturee avant l'increment).

**`search_articles`** : `icontains` simple sur `title`/`body`, articles
PUBLIES uniquement — pas de moteur de recherche plein texte dedie ici,
`core.services.search.global_search` existe deja pour une recherche
plein texte cross-module mais necessite un enregistrement actif
(`register_search_source` + reindexation a chaque creation/modification,
cf. `apps.core.services.search_registry`) : **decision disclosed** de ne
PAS brancher `HlpKbArticle` dans ce mecanisme pour ce lot HD3 — aucun
module metier de ce depot ne l'a encore fait a ce jour (verifie :
`register_search_source` n'est utilise nulle part hors des tests `core`
eux-memes), et le cabler correctement (reindexation a la publication/
depublication/edition, gestion du retrait au softdelete) serait une
extension de perimetre non requise par HD3 — un simple `icontains` suffit
amplement au volume attendu d'une base de connaissances interne. A
reconsiderer si un besoin reel de recherche plein texte/tolerante aux
fautes de frappe sur la KB se precise plus tard."""

from __future__ import annotations

from django.db.models import F, Q, QuerySet

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.helpdesk.models import HlpKbArticle, HlpKbCategory


def create_article(
    tenant: Tenant,
    *,
    title: str,
    body: str = "",
    category: HlpKbCategory | None = None,
    author: User | None = None,
    is_published: bool = False,
    created_by: User | None = None,
) -> HlpKbArticle:
    return HlpKbArticle.objects.create(
        tenant=tenant,
        title=title,
        body=body,
        category=category,
        author=author,
        is_published=is_published,
        created_by=created_by,
    )


def publish_article(article: HlpKbArticle) -> HlpKbArticle:
    """Simple bascule booleenne — pas une FSM, cf. plan (« pas besoin de
    FSM, juste un flag »)."""
    article.is_published = True
    article.save(update_fields=["is_published"])
    return article


def unpublish_article(article: HlpKbArticle) -> HlpKbArticle:
    article.is_published = False
    article.save(update_fields=["is_published"])
    return article


def record_article_view(article: HlpKbArticle) -> HlpKbArticle:
    HlpKbArticle.objects.filter(pk=article.pk).update(view_count=F("view_count") + 1)
    article.refresh_from_db(fields=["view_count"])
    return article


def record_article_feedback(article: HlpKbArticle, *, helpful: bool) -> HlpKbArticle:
    field = "helpful_count" if helpful else "not_helpful_count"
    HlpKbArticle.objects.filter(pk=article.pk).update(**{field: F(field) + 1})
    article.refresh_from_db(fields=[field])
    return article


def search_articles(tenant: Tenant, query: str) -> QuerySet[HlpKbArticle]:
    queryset = HlpKbArticle.objects.filter(tenant=tenant, is_active=True, is_published=True)
    if not query:
        return queryset
    return queryset.filter(Q(title__icontains=query) | Q(body__icontains=query))
