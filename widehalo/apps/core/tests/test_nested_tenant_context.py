"""S6 — `activate_tenant` imbriqué RÉTABLIT la société précédente.

**Le défaut, trouvé en écrivant la purge de charge utile de FLX-5.** La
version d'origine appelait `clear_current_tenant()` en sortie de bloc.
Tant qu'`activate_tenant` n'était employé qu'au premier niveau — une
commande de management, une tâche de fond — cela revenait au même.

Mais douze services de ce dépôt BOUCLENT sur les sociétés (`reporting.
purge_expired_jobs`, `core.sandbox.purge_expired_sandboxes`, la
planification des rapports, la purge de charge utile…). Dès que l'un
d'eux est appelé depuis un contexte déjà actif — une requête HTTP, dont
`TenantMiddleware` a posé la société, ou un test —, la sortie du bloc
imbriqué laissait l'appelant SANS société.

Et c'est là que ça devient grave plutôt que gênant : `TenantManager` est
deny-by-default. Hors contexte, il ne lève pas, il renvoie `none()`. Toute
lecture suivante rendait donc un ensemble vide, sans erreur, sans journal,
sans rien — un écran vide qu'on met une journée à diagnostiquer.
`apps/reporting/views.py` et `apps/reporting/api.py` appellent tous deux
`activate_tenant` en pleine requête.

Le contextvar rend un JETON précisément pour ça, et il n'était pas
utilisé.
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def deux_societes():
    a = Tenant.objects.create(code="CTX-A", name="Société A")
    b = Tenant.objects.create(code="CTX-B", name="Société B")
    return a, b


def _reglage_postgres() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.tenant_id', true)")
        return cursor.fetchone()[0] or ""


def test_the_outer_company_survives_an_inner_block(deux_societes) -> None:
    a, b = deux_societes
    with use_tenant(a.id):
        assert get_current_tenant_id() == str(a.id)
        with activate_tenant(b.id):
            assert get_current_tenant_id() == str(b.id)
        assert get_current_tenant_id() == str(a.id), (
            "Le bloc imbriqué a remis à zéro au lieu de rétablir : tout ce "
            "qui suit lit désormais un ensemble vide, en silence."
        )


def test_postgresql_also_comes_back_to_the_outer_company(deux_societes) -> None:
    """L'autre moitié du même défaut, et elle ne se déduit pas de la
    première. `SET LOCAL` est porté par la transaction : sur un bloc
    imbriqué — donc un point de sauvegarde — il n'est PAS repris au
    relâchement. Le filtre Django aurait dit une société, la policy
    PostgreSQL une autre."""
    a, b = deux_societes
    with use_tenant(a.id):
        with activate_tenant(b.id):
            assert _reglage_postgres() == str(b.id)
        assert _reglage_postgres() == str(a.id)


def test_reading_still_works_after_an_inner_block(deux_societes) -> None:
    """La conséquence observable, et la seule qui compte vraiment : une
    lecture ordinaire après le bloc imbriqué doit rendre les lignes de la
    société d'origine. Sans ce test, les deux précédents vérifieraient une
    mécanique sans jamais toucher à son effet."""
    a, b = deux_societes
    with use_tenant(a.id):
        SampleTenantScopedRecord.objects.create(tenant=a, label="chez A")

    with use_tenant(a.id):
        avant = SampleTenantScopedRecord.objects.count()
        with activate_tenant(b.id):
            SampleTenantScopedRecord.objects.create(tenant=b, label="chez B")
        apres = SampleTenantScopedRecord.objects.count()

    assert avant == 1
    assert apres == 1, (
        "Après le bloc imbriqué, la lecture rend un ensemble vide : c'est "
        "exactement le mode d'échec silencieux de `TenantManager`."
    )


def test_the_context_is_still_cleared_when_there_was_nothing_to_restore(
    deux_societes,
) -> None:
    """Le témoin. Rétablir ne doit pas devenir « ne jamais sortir » : hors
    de tout contexte, on doit ressortir hors de tout contexte, sans quoi la
    protection deny-by-default de `TenantManager` disparaîtrait.

    **Côté PostgreSQL, au premier niveau, il n'y a rien à rétablir et c'est
    voulu.** Le bloc atomique qui portait le `SET LOCAL` se termine avec
    lui : en production, PostgreSQL oublie le réglage tout seul. En test,
    pytest-django tient une transaction englobante, si bien que le réglage
    survit à la sortie du bloc — et c'est de cette survivance que dépendent
    toutes les lectures faites par `refresh_from_db` après un
    `use_tenant`, dans tout le dépôt. Ce test constate donc l'état réel
    plutôt que d'affirmer un idéal que le dépôt entier contredit."""
    a, _b = deux_societes
    assert get_current_tenant_id() is None
    with activate_tenant(a.id):
        assert get_current_tenant_id() == str(a.id)
    assert get_current_tenant_id() is None, (
        "Le côté Django, lui, ressort bien de toute société : c'est la "
        "protection deny-by-default de `TenantManager`."
    )


def test_an_exception_inside_the_inner_block_still_restores(deux_societes) -> None:
    """Le chemin d'erreur, qui est celui qu'on oublie. Le rétablissement
    PostgreSQL n'est délibérément PAS dans un `finally` — la transaction
    peut être avortée, et une instruction de plus lèverait à son tour en
    masquant la cause. C'est l'annulation elle-même qui reprend les
    `SET LOCAL` posés depuis le point de sauvegarde ; ce test le vérifie
    plutôt que de le supposer."""
    a, b = deux_societes
    with use_tenant(a.id):
        with pytest.raises(RuntimeError), activate_tenant(b.id):
            raise RuntimeError("quelque chose a mal tourné")
        assert get_current_tenant_id() == str(a.id)
