"""T6 — Matrice RBAC role x endpoint (couche 9 du CDC : RBAC granulaire).

Ce module etend l'approche de `test_rbac_default_deny.py` (qui verifie le
mecanisme `require_permission` en isolation, sur une vue factice) a la
surface REELLE de l'API : chaque operation django-ninja montee sur
`config.api.api`, tous routers confondus (socle Lot 1 + modules metier
Lot 2 : accounting, crm, mrp, patronage, partners, catalog, chat...).

Historique : au 27/08/2026 (constat initial de ce module), AUCUNE
operation montee n'utilisait `require_permission()` — seule
l'authentification JWT par defaut (401 anonyme) protegeait la surface
API ; un utilisateur authentifie, quel que soit son role, atteignait
n'importe quel endpoint metier. Ce constat a depuis ete corrige (meme
session, T6) : `require_permission` est maintenant applique a tous les
endpoints des modules metier (accounting, crm, mrp, patronage, partners,
catalog) via `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS`. Seuls
restent volontairement hors perimetre : `chat` (messagerie interne
transversale, cf. docstring de `rbac_policy`) et une poignee d'endpoints
plateforme Lot 1 sans modele metier direct (tenants, recherche globale,
notifications, exports, approbations, echo de sante) — voir
`EXPECTED_UNDECLARED_PATHS` ci-dessous.

Ce test :
1. Enumere statiquement toutes les operations montees (methode, chemin,
   fonction, tags/router, `auth=None` ou non, permission declaree via
   `require_permission`).
2. Verifie empiriquement, via de vraies requetes HTTP (`django.test.Client`)
   et de vrais JWT mintes pour un utilisateur par role, que :
   - un appel anonyme sur une operation protegee recoit 401 (baseline
     deny-by-default, appliquee partout) ;
   - pour les operations GET sans parametre de chemin (probables sans
     fixture prealable), chaque role recoit 403 si et seulement si il ne
     possede pas (via son Group Django, synchronise par
     `sync_group_permissions`) la permission declaree par l'endpoint —
     preuve empirique que la granularite N2 est desormais reellement
     appliquee, pas seulement declaree dans le code.
3. Ecrit un rapport lisible (`rbac_matrix_report.txt`, a cote de ce
   fichier) resumant la couverture par tag/router et le detail role x
   endpoint des operations sondees, pour revue humaine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from config.api import api
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from ninja_jwt.tokens import RefreshToken

from apps.core.models.tenant import Tenant
from apps.core.models.user import User

pytestmark = pytest.mark.django_db

REPORT_PATH = Path(__file__).resolve().parent / "rbac_matrix_report.txt"

ROLES: list[str] = list(settings.CORE_STANDARD_ROLES)

# Bug de routage decouvert par ce test (non corrige ici, cf. rapport et
# message de fin de mission — hors perimetre "tests seulement") :
# apps/partners/api.py declare `GET /partners/{partner_id}` avant
# `POST /partners/merge`. Le convertisseur de chemin de {partner_id} est un
# `str` qui matche aussi le segment litteral "merge", et Django/ninja
# resout les URLs dans l'ordre de declaration : toute requete sur
# /partners/merge (quel que soit son verbe HTTP) est donc capturee par le
# PathView de /partners/{partner_id}, qui ne connait que GET -> 405 Method
# Not Allowed, AVANT meme que l'authentification/l'auth JWT ne soit
# evaluee. `merge_endpoint` (la fonction Python) est de fait inatteignable
# via HTTP tant que cet ordre de declaration n'est pas corrige. Ce n'est
# pas une garde RBAC : c'est un defaut de routage qui masque presentement
# tout defaut de RBAC sur cette operation precise.
KNOWN_ROUTING_SHADOWED: dict[tuple[str, str], int] = {("POST", "/partners/merge"): 405}

# Endpoints intentionnellement hors perimetre RBAC N2 de ce lot (T6) :
# `chat` (messagerie interne transversale, pas de donnee metier sensible —
# cf. docstring de `apps.core.services.rbac_policy`) et une poignee
# d'endpoints plateforme Lot 1 qui ne correspondent a aucun modele
# "vue/ajout/modification" d'un module metier et restent donc hors de
# `ROLE_APP_PERMISSIONS`. Si un NOUVEL endpoint apparait sans permission
# et sans etre liste ici, `test_all_business_endpoints_declare_a_
# required_permission` echoue — c'est le garde-fou anti-regression.
EXPECTED_UNDECLARED_PATHS: set[tuple[str, str]] = {
    ("GET", "/chat/channels"),
    ("GET", "/chat/channels/{channel_id}/messages"),
    ("POST", "/chat/channels/{channel_id}/messages"),
    ("POST", "/meta/echo"),
    ("GET", "/tenants"),
    ("POST", "/tenants/select"),
    ("GET", "/search"),
    ("GET", "/notifications"),
    ("POST", "/notifications/{notification_id}/read"),
    ("GET", "/exports"),
    ("GET", "/approvals/pending"),
    ("POST", "/approvals/{request_id}/decide"),
    # AI2 (assistant contextuel par page/action) : posture RBAC deliberement
    # ouverte a tout role authentifie, cadrage explicite du plan — meme
    # raisonnement que les endpoints `chat` ci-dessus (aucun modele metier
    # direct, guidance utile a n'importe quel role en train de travailler).
    ("POST", "/ai/assist"),
    ("GET", "/ai/assist/modules"),
    # AI4 (recherche en langage naturel) : meme posture ouverte, meme
    # raisonnement — cf. docstring de tete de `apps/ai/api.py` (route vers
    # `global_search`, deja tenant-scope et deja filtre RBAC par resultat,
    # meme posture que `GET /search` ci-dessus).
    ("POST", "/ai/search"),
    # AI5 (insights proactifs automatises) : meme posture ouverte — cf.
    # docstring de tete de `apps/ai/api.py` (rbac_policy.py earmarque
    # nommement les « insights » aux cotes de l'assistant contextuel/la
    # recherche pour cette posture, contrairement aux anomalies AI3 dont
    # la posture restreinte est un choix pragmatique ulterieur disclosed).
    ("POST", "/ai/insights/generate"),
    ("GET", "/ai/insights"),
    # AI7 (advisor d'actions/next-best-action) : meme posture ouverte —
    # `rbac_policy.py` earmarque nommement "recommandations" au meme titre
    # qu'assistant/recherche/insights des AI1 (aucune deviation cette fois,
    # contrairement a AI5 qui avait du confirmer par lecture de code).
    ("POST", "/ai/recommendations"),
    ("GET", "/ai/recommendations"),
    # GW4 (passerelle IA locale d'analyse de donnees) : meme posture ouverte
    # que les endpoints AI2/AI4/AI5/AI7 ci-dessus — la vraie restriction de
    # securite est DEPLACEE a l'interieur de `data_query_gateway.ask()` (un
    # `required_permission` par tool, verifie AVANT que le tool soit meme
    # propose au LLM), pas un `require_permission` global sur l'endpoint
    # lui-meme (cf. docstring de tete de `apps/ai/api.py`).
    ("POST", "/ai/data-query/ask"),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    module: str
    name: str
    tags: tuple[str, ...]
    is_public: bool
    required_permission: str | None

    @property
    def has_path_params(self) -> bool:
        return "{" in self.path


def _iter_operations() -> list[Operation]:
    """Introspecte `config.api.api._routers` : c'est la seule source de
    verite sur ce qui est reellement monte (Lot 1 socle + Lot 2 metier),
    conformement au principe API-first du CDC."""
    ops: list[Operation] = []
    for prefix, router in api._routers:
        tags = tuple(getattr(router, "tags", None) or ())
        for path, view in router.path_operations.items():
            for op in view.operations:
                fn = op.view_func
                is_public = op.auth_param is None
                required = getattr(fn, "_required_permission", None)
                for method in sorted(op.methods):
                    ops.append(
                        Operation(
                            method=method,
                            path=f"{prefix}{path}",
                            module=fn.__module__,
                            name=fn.__name__,
                            tags=tags,
                            is_public=is_public,
                            required_permission=required,
                        )
                    )
    return ops


ALL_OPERATIONS: list[Operation] = _iter_operations()
PROTECTED_OPERATIONS = [op for op in ALL_OPERATIONS if not op.is_public]
PUBLIC_OPERATIONS = [op for op in ALL_OPERATIONS if op.is_public]

# GET sans parametre de chemin : sondables sans fixture metier prealable
# (pas de body a construire, pas d'ID a faire exister). Les operations de
# mutation/detail sont documentees dans le rapport mais pas invoquees
# reellement (cf. docstring du module et section 4 du prompt d'origine).
PROBEABLE_OPERATIONS = [
    op for op in PROTECTED_OPERATIONS if op.method == "GET" and not op.has_path_params
]


def _mint_token(user: User) -> str:
    return str(RefreshToken.for_user(user).access_token)


def _call(client: Client, op: Operation, token: str | None, tenant_id: str):
    headers: dict[str, str] = {"HTTP_X_TENANT_ID": tenant_id}
    if token:
        headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client.generic(op.method, f"/api/v1{op.path}", **headers)


def test_all_business_endpoints_declare_a_required_permission() -> None:
    """Garde-fou anti-regression sur la couverture du fix T6 : tout
    endpoint protege des modules metier (accounting, crm, mrp, patronage,
    partners, catalog) doit declarer une permission N2 via
    `require_permission`. Seuls les endpoints listes dans
    `EXPECTED_UNDECLARED_PATHS` (chat + endpoints plateforme Lot 1 sans
    modele metier direct) en restent dispenses. Si ce test echoue parce
    qu'un NOUVEL endpoint metier est ajoute sans permission declaree,
    c'est une regression du principe deny-by-default a corriger — pas ce
    test."""
    undeclared = [
        op
        for op in PROTECTED_OPERATIONS
        if not op.required_permission and (op.method, op.path) not in EXPECTED_UNDECLARED_PATHS
    ]
    assert undeclared == [], (
        "Endpoint(s) protege(s) sans permission N2 declaree (require_permission) "
        "et absent(s) de EXPECTED_UNDECLARED_PATHS :\n"
        + "\n".join(f"{op.method} {op.path}" for op in undeclared)
    )


def test_anonymous_is_denied_on_every_protected_operation() -> None:
    """Etend le test generique 'anonymous -> 401' de
    test_rbac_default_deny.py (qui ne teste qu'une vue factice) a TOUTES
    les operations reellement montees, socle + Lot 2 metier inclus."""
    client = Client()
    tenant = Tenant.objects.create(code="RBAC-ANON", name="RBAC anonymous baseline")
    failures = []
    for op in PROTECTED_OPERATIONS:
        expected = KNOWN_ROUTING_SHADOWED.get((op.method, op.path), 401)
        response = _call(client, op, token=None, tenant_id=str(tenant.id))
        if response.status_code != expected:
            failures.append(f"{op.method} {op.path} -> {response.status_code} (attendu {expected})")
    assert not failures, "Endpoints protégés accessibles sans authentification:\n" + "\n".join(
        failures
    )


def test_partners_merge_is_shadowed_by_partner_detail_route() -> None:
    """Garde-fou explicite pour le bug de routage documente ci-dessus :
    si `apps/partners/api.py` est un jour corrige (ex. declarant
    `/partners/merge` avant `/partners/{partner_id}`), ce test echouera
    et rappellera de retirer l'entree correspondante de
    KNOWN_ROUTING_SHADOWED / cette assertion."""
    client = Client()
    tenant = Tenant.objects.create(code="RBAC-ROUTING", name="RBAC routing bug check")
    response = client.post(
        "/api/v1/partners/merge",
        data="{}",
        content_type="application/json",
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 405, (
        "POST /partners/merge ne renvoie plus 405 : le bug de routage "
        "(GET /partners/{partner_id} declare avant POST /partners/merge, "
        "cf. commentaire KNOWN_ROUTING_SHADOWED) semble corrige — retirer "
        "l'entree correspondante et ce test, et sonder reellement "
        "l'endpoint dans la matrice RBAC."
    )


def test_rbac_matrix_report(request: pytest.FixtureRequest) -> None:
    """Construit la matrice role x endpoint (empirique, requetes HTTP
    reelles) pour les operations GET sans parametre de chemin, et ecrit
    un rapport texte complet (toutes operations, sondees ou non) pour
    revue humaine. Assertion : le resultat observe correspond exactement
    a la permission N2 declaree par chaque endpoint —
    - endpoint sans permission declaree (`EXPECTED_UNDECLARED_PATHS`) :
      jamais de 403 (comportement legacy assume, hors perimetre) ;
    - endpoint avec permission declaree : 403 SI ET SEULEMENT SI le role
      sonde n'a pas cette permission (via son Group Django, synchronise
      par `sync_group_permissions`/`load_roles`)."""
    call_command("load_roles")
    groups = {g.name: g for g in Group.objects.filter(name__in=ROLES)}
    assert set(groups) == set(ROLES), "load_roles n'a pas cree les 11 roles standards attendus"

    client = Client()
    tenant = Tenant.objects.create(code="RBAC-MATRIX", name="RBAC matrix tenant")

    tokens: dict[str, str] = {}
    role_permissions: dict[str, set[str]] = {}
    for role in ROLES:
        user = User.objects.create_user(
            email=f"rbac-matrix-{role}@example.com", password="Str0ngPassw0rd!23"
        )
        user.groups.add(groups[role])
        tokens[role] = _mint_token(user)
        role_permissions[role] = set(user.get_all_permissions())

    matrix: dict[Operation, dict[str, int]] = {}
    for op in PROBEABLE_OPERATIONS:
        row: dict[str, int] = {}
        for role in ROLES:
            response = _call(client, op, token=tokens[role], tenant_id=str(tenant.id))
            row[role] = response.status_code
        matrix[op] = row

    report = _render_report(matrix)
    REPORT_PATH.write_text(report, encoding="utf-8")
    # Rend le rapport visible dans la sortie pytest (-s) sans dependre
    # uniquement du fichier ecrit sur disque.
    request.node.add_report_section("call", "rbac-matrix", report)

    mismatches = []
    for op, row in matrix.items():
        is_exempt = (op.method, op.path) in EXPECTED_UNDECLARED_PATHS
        for role, code in row.items():
            if code == 422:
                # Parametres de query obligatoires manquants (ex.
                # `fiscal_year_id`, `pipeline_id`) : ninja valide/parse
                # les parametres AVANT d'invoquer `view_func` (donc avant
                # que `require_permission` ne s'execute), pour tout role.
                # Un sondage "GET sans body" ne fournit pas ces valeurs —
                # inconcluant pour la RBAC, ni conforme ni en ecart.
                continue
            if not op.required_permission or is_exempt:
                if code == 403:
                    mismatches.append(
                        f"{op.method} {op.path} role={role} -> 403 alors qu'aucune "
                        "permission N2 n'est declaree (ou endpoint exempte)"
                    )
                continue
            has_perm = op.required_permission in role_permissions[role]
            if has_perm and code == 403:
                mismatches.append(
                    f"{op.method} {op.path} role={role} -> 403 alors que ce role "
                    f"possede la permission declaree ({op.required_permission})"
                )
            elif not has_perm and code != 403:
                mismatches.append(
                    f"{op.method} {op.path} role={role} -> {code} (attendu 403 : "
                    f"ce role n'a pas la permission declaree {op.required_permission})"
                )
    assert not mismatches, (
        "Ecart entre la permission N2 declaree par require_permission et le "
        "comportement HTTP observe :\n" + "\n".join(mismatches)
    )


def _render_report(matrix: dict[Operation, dict[str, int]]) -> str:
    lines: list[str] = []
    lines.append("=" * 100)
    lines.append("RAPPORT RBAC — Matrice role x endpoint (T6, couche 9 CDC)")
    lines.append(
        f"Genere le 2026-08-27 — {len(ALL_OPERATIONS)} operations montees sur config.api.api"
    )
    lines.append("=" * 100)
    lines.append("")
    lines.append(
        "MECANISME TROUVE : require_permission(codename) — decorateur declaratif dans "
        "apps/core/services/permissions.py. Verifie request.auth (401 si absent), puis "
        "user.has_perm(codename) (403 sinon), AVANT le corps de la vue (donc avant toute "
        "validation de payload)."
    )
    declared_count = sum(1 for op in PROTECTED_OPERATIONS if op.required_permission)
    lines.append(
        f"CONSTAT (mis a jour, fix T6) : {declared_count}/{len(PROTECTED_OPERATIONS)} "
        "endpoints proteges declarent desormais une permission N2 via require_permission(). "
        "Les endpoints restants sont volontairement hors perimetre (chat + endpoints "
        "plateforme Lot 1 sans modele metier, cf. EXPECTED_UNDECLARED_PATHS) — voir "
        "test_all_business_endpoints_declare_a_required_permission."
    )
    lines.append("")
    lines.append(
        "BUG DE ROUTAGE DECOUVERT (hors RBAC, non corrige par ce test) : "
        "POST /partners/merge est shadowe par GET /partners/{partner_id} "
        "(declare avant dans apps/partners/api.py ; le convertisseur str "
        "de {partner_id} matche aussi le segment litteral 'merge'). "
        "Consequence : toute requete POST /partners/merge recoit 405 "
        "avant meme l'evaluation de l'authentification/RBAC — "
        "`merge_endpoint` est inatteignable via HTTP en l'etat. "
        "Voir KNOWN_ROUTING_SHADOWED et test_partners_merge_is_shadowed_"
        "by_partner_detail_route dans ce fichier."
    )
    lines.append("")

    by_tag: dict[str, list[Operation]] = {}
    for op in ALL_OPERATIONS:
        tag = op.tags[0] if op.tags else "(sans tag)"
        by_tag.setdefault(tag, []).append(op)

    lines.append("-" * 100)
    lines.append("RESUME PAR ROUTER / TAG")
    lines.append("-" * 100)
    header = f"{'tag':<16}{'total':>7}{'public':>8}{'protege':>9}{'perm. declaree':>16}"
    lines.append(header)
    for tag in sorted(by_tag):
        ops = by_tag[tag]
        total = len(ops)
        public = sum(1 for op in ops if op.is_public)
        protected = total - public
        declared = sum(1 for op in ops if op.required_permission)
        lines.append(f"{tag:<16}{total:>7}{public:>8}{protected:>9}{declared:>16}")
    lines.append("")

    lines.append("-" * 100)
    lines.append(f"ROLES SONDES ({len(ROLES)}) : " + ", ".join(ROLES))
    lines.append("-" * 100)
    lines.append("")

    lines.append("-" * 100)
    lines.append(
        f"MATRICE EMPIRIQUE — GET sans parametre de chemin ({len(matrix)} endpoints x "
        f"{len(ROLES)} roles, requetes HTTP reelles via un JWT par role)"
    )
    lines.append("-" * 100)
    col_w = 8
    lines.append(f"{'endpoint':<40}" + "".join(f"{r[:7]:>{col_w}}" for r in ROLES))
    for op, row in sorted(matrix.items(), key=lambda kv: kv[0].path):
        label = f"{op.method} {op.path}"
        lines.append(f"{label:<40}" + "".join(f"{row[r]:>{col_w}}" for r in ROLES))
    lines.append("")
    lines.append(
        "Lecture : 403 = role sans la permission N2 declaree pour cet endpoint ; "
        "200/autre = role autorise (ou endpoint sans permission declaree, cf. "
        "EXPECTED_UNDECLARED_PATHS) ; 422 = parametre(s) de requete obligatoire(s) "
        "manquant(s) (le sondage GET sans body ne les fournit pas) — ninja valide "
        "les parametres AVANT d'invoquer la vue, donc AVANT require_permission : "
        "inconcluant pour tous les roles, non teste par l'assertion de ce test."
    )
    lines.append("")

    not_probed = [
        op for op in PROTECTED_OPERATIONS if not (op.method == "GET" and not op.has_path_params)
    ]
    lines.append("-" * 100)
    lines.append(
        f"ENDPOINTS PROTEGES NON SONDES EMPIRIQUEMENT ({len(not_probed)}) — mutations "
        "(POST/PATCH/DELETE) et/ou endpoints avec parametre(s) de chemin nécessitant des "
        "fixtures metier (ID existant, body valide) pour etre exerces sans erreur non liee "
        "a la RBAC. Verifie uniquement statiquement ici (permission declaree ou non, "
        "colonne 'perm. declaree' du resume par tag) ; leur application effective repose "
        "sur le meme mecanisme require_permission que les endpoints sondes ci-dessus."
    )
    lines.append("-" * 100)
    for op in sorted(not_probed, key=lambda o: (o.tags, o.path, o.method)):
        tag = op.tags[0] if op.tags else "(sans tag)"
        lines.append(f"  [{tag:<12}] {op.method:<6} {op.path}")
    lines.append("")

    lines.append("-" * 100)
    lines.append(f"ENDPOINTS PUBLICS (auth=None, {len(PUBLIC_OPERATIONS)}) — hors perimetre RBAC")
    lines.append("-" * 100)
    for op in sorted(PUBLIC_OPERATIONS, key=lambda o: (o.tags, o.path, o.method)):
        tag = op.tags[0] if op.tags else "(sans tag)"
        lines.append(f"  [{tag:<12}] {op.method:<6} {op.path}")
    lines.append("")

    return "\n".join(lines)
