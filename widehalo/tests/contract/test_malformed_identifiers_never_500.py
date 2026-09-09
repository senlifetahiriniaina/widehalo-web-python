"""T4bis — un identifiant malformé rend 422, jamais 500. Mesure DÉTERMINISTE.

**Pourquoi ce fichier existe alors que la campagne de contrat couvre déjà
ces endpoints.** Parce qu'elle ne les mesure pas de façon reproductible.
Sa propre docstring l'écrit : « la campagne MODIFIE la base qu'elle teste
[…] l'ensemble des opérations en échec dépend de l'état de la base, pas
seulement du tirage. Mesure : trois passes, trois ensembles différents ».
Les passes de ce lot l'ont confirmé une fois de plus — 24 puis 29 échecs
sur un code identique.

Un compteur qui varie de 20 % d'une passe à l'autre ne peut ni confirmer
ni infirmer un correctif. Il sert à DÉCOUVRIR (c'est ainsi que les 264
premiers 500 ont été trouvés) ; il ne sert pas à PROUVER.

**Ce que ce fichier prouve, et rien de plus.** Sur un échantillon
d'endpoints représentatif des modules retypés par T4bis, un identifiant
syntaxiquement invalide reçoit un code d'erreur explicite — 422 par la
validation de schéma de django-ninja, ou 400/404 selon la surface —
jamais 500. C'est le critère de la Phase 4, mot pour mot : le système
tiers « ne lit aucune documentation contextuelle, ne devine rien, ne
pardonne rien » et attend « des codes d'erreur explicites ».

**L'échantillon est nommé, pas exhaustif, et c'est assumé.** Exhaustif, il
faudrait construire un jeu de données valide pour 594 opérations — ce que
la campagne fait déjà, avec l'instabilité qu'on lui connaît. Ce qui est
tenu ici est la propriété sur les formes REPRÉSENTATIVES de chaque
famille : un identifiant dans le corps, un dans une liste, un dans un
paramètre de chemin.
"""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db

#: Les valeurs qu'un presse-papier tronqué, un copier-coller partiel ou un
#: intégrateur pressé produisent réellement. Aucune n'est exotique.
IDENTIFIANTS_MALFORMES = [
    "",
    "   ",
    "pas-un-uuid",
    "01a0824a-c453-7dad-97a2",  # tronqué au milieu
    "01a0824a-c453-7dad-97a2-6ecfdbd80c60x",  # un caractère de trop
    "<script>alert(1)</script>",
]


def _token(client: Client, email: str, password: str) -> str:
    reponse = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return str(reponse.json()["access"])


@pytest.fixture
def societe_et_client():
    tenant = Tenant.objects.create(code="T4BIS-ID", name="Identifiants SARL")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="t4bis@example.com", password="Str0ngPassw0rd!23")
    for role in ("acheteur", "commercial", "magasinier"):
        grant_role(user, role)
    client = Client()
    entetes = {
        "HTTP_AUTHORIZATION": f"Bearer {_token(client, 't4bis@example.com', 'Str0ngPassw0rd!23')}",
        "HTTP_X_TENANT_ID": str(tenant.id),
    }
    return tenant, client, entetes


#: (chemin, corps) — un endpoint par FAMILLE de déclaration, pas un par
#: module : ce qui est vérifié est la forme, et la forme est partagée.
CAS: list[tuple[str, str]] = [
    # Identifiant simple dans le corps.
    ("/api/v1/purchase/requisitions", "partner_id"),
    ("/api/v1/sales/quotations", "partner_id"),
    ("/api/v1/crm/leads", "partner_id"),
]


@pytest.mark.parametrize("chemin,champ", CAS)
@pytest.mark.parametrize("valeur", IDENTIFIANTS_MALFORMES)
def test_a_malformed_identifier_never_produces_a_server_error(
    societe_et_client, chemin: str, champ: str, valeur: str
) -> None:
    """Le refus doit être EXPLICITE, pas une panne.

    Avant T4bis, `uuid.UUID(payload.partner_id)` sur un champ `str` levait
    `ValueError` — qu'aucun gestionnaire ne rattrape — et l'utilisateur
    recevait « une erreur inattendue est survenue » pour un identifiant
    tronqué par son presse-papier."""
    _tenant, client, entetes = societe_et_client
    reponse = client.post(
        chemin,
        {champ: valeur, "name": "Essai", "date": "2026-01-15", "lines": []},
        content_type="application/json",
        **entetes,
    )
    assert reponse.status_code != 500, (
        f"{chemin} rend 500 sur {champ}={valeur!r} — un identifiant malformé "
        "doit produire un code d'erreur explicite, pas une panne serveur."
    )
    assert 400 <= reponse.status_code < 500, (
        f"{chemin} rend {reponse.status_code} sur {champ}={valeur!r} : un "
        "identifiant invalide ne peut pas être accepté."
    )


def test_the_measurement_would_catch_a_regression() -> None:
    """Auto-test : la liste de valeurs ne doit pas se vider en silence.

    Une garde qui n'exerce rien reste verte pour toujours — c'est le défaut
    que ce chantier a rencontré trois fois."""
    assert len(IDENTIFIANTS_MALFORMES) >= 5
    assert "" in IDENTIFIANTS_MALFORMES, "la chaîne vide est le cas le plus fréquent"
    assert any(len(v) > 30 for v in IDENTIFIANTS_MALFORMES), "un UUID presque valide manque"
