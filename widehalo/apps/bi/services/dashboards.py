"""L9 — la voie d'ECRITURE des tableaux de bord, qui n'existait pas.

**Le defaut ferme.** `BiDashboard` avait SIX occurrences dans tout le
depot — sa definition, sa migration de schema, un import et une lecture
dans la vue, et une factory de test jamais utilisee. Aucun
`objects.create`, aucune route d'API d'ecriture (`apps/bi/api.py`
n'expose que deux lectures), aucune commande, aucune fixture, aucun
enregistrement dans l'admin Django.

Or l'onglet PAR DEFAUT de `/bi/` est `dashboards` (`views.py:51`) : le
premier ecran que voit tout utilisateur du module affichait « Aucun
tableau de bord pour votre role ». Structurellement, et sur toute
instance. Aucun test n'echouait — puisque aucun test n'en creait.

Le modele etait pret (tuiles denormalisees, `role_code`, `owner`,
`is_shared`) et la vue savait deja filtrer et resoudre les tuiles. Il ne
manquait que ceci."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.bi.models import BiDashboard, BiReport
from apps.core.models.tenant import Tenant
from apps.core.models.user import User

TILE_SIZES = ("sm", "md", "lg")


def _validated_tiles(tenant: Tenant, tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise et VERIFIE les tuiles avant persistance.

    `tiles` est un JSONField denormalise : rien en base n'empeche d'y
    ecrire l'UUID d'un rapport inexistant, ou appartenant a un autre
    tenant. Un tableau de bord dont une tuile ne resout pas s'affiche
    silencieusement amputee — le lecteur croit voir tout son tableau. La
    verification a lieu ICI, une fois, plutot qu'a chaque rendu.

    Les rapports sont cherches DANS LE TENANT : c'est ce qui empeche de
    composer un tableau de bord pointant sur le rapport d'une autre
    societe."""
    known = set(BiReport.objects.filter(tenant=tenant).values_list("id", flat=True))
    normalised: list[dict[str, Any]] = []
    for position, tile in enumerate(tiles):
        raw_id = tile.get("report_id")
        try:
            report_id = UUID(str(raw_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("Tuile %(position)s : identifiant de rapport invalide.")
                % {"position": position + 1}
            ) from exc
        if report_id not in known:
            raise ValidationError(
                _("Tuile %(position)s : ce rapport n'existe pas dans cette société.")
                % {"position": position + 1}
            )
        size = tile.get("size", "md")
        if size not in TILE_SIZES:
            raise ValidationError(
                _("Tuile %(position)s : taille %(size)s inconnue.")
                % {"position": position + 1, "size": size}
            )
        normalised.append(
            {"report_id": str(report_id), "position": tile.get("position", position), "size": size}
        )
    return normalised


def create_dashboard(
    tenant: Tenant,
    *,
    name: str,
    user: User,
    role_code: str = "",
    tiles: list[dict[str, Any]] | None = None,
    is_shared: bool = False,
) -> BiDashboard:
    """Cree un tableau de bord — personnel, ou par defaut pour un role.

    `role_code` non vide = tableau de bord PAR DEFAUT du role, visible de
    tous ses porteurs ; vide = tableau personnel, dont `owner` est
    l'auteur. La docstring du modele posait deja cette regle (« `owner`
    alors obligatoire cote service ») sans qu'aucun service ne la tienne :
    c'est ici qu'elle devient vraie."""
    name = name.strip()
    if not name:
        raise ValidationError(_("Le nom du tableau de bord est obligatoire."))
    return BiDashboard.objects.create(
        tenant=tenant,
        name=name,
        owner=user,
        role_code=role_code.strip(),
        tiles=_validated_tiles(tenant, tiles or []),
        is_shared=is_shared,
        created_by=user,
    )


def set_dashboard_tiles(dashboard: BiDashboard, *, tiles: list[dict[str, Any]]) -> BiDashboard:
    """Recompose les tuiles d'un tableau de bord existant."""
    dashboard.tiles = _validated_tiles(dashboard.tenant, tiles)
    dashboard.save(update_fields=["tiles"])
    return dashboard


def ensure_starting_dashboards(tenant: Tenant, *, user: User | None = None) -> list[BiDashboard]:
    """Jeu de depart : un tableau de bord par role, compose des rapports
    PUBLIES que ce role peut deja voir.

    **Pourquoi un amorcage plutot qu'un ecran seul.** Livrer la voie
    d'ecriture sans jeu de depart laisserait le premier ecran du module
    vide jusqu'a ce que quelqu'un compose son premier tableau — c'est-a-
    dire le meme ecran vide, avec une explication. Meme patron d'amorcage
    que `analytics.services.starting_metrics` (L8), et meme discipline :
    idempotent, et n'ecrase JAMAIS un tableau que le tenant a modifie.

    Les tuiles sont construites depuis les rapports REELLEMENT publies du
    tenant : un jeu de depart qui referencerait des codes de rapport
    attendus mais absents recreerait exactement le defaut d'origine — des
    tuiles qui ne resolvent pas."""
    reports = list(
        BiReport.objects.filter(tenant=tenant, is_published=True).order_by("domaine", "name")
    )
    if not reports:
        return []

    created: list[BiDashboard] = []
    by_domain: dict[str, list[BiReport]] = {}
    for report in reports:
        by_domain.setdefault(report.domaine or "general", []).append(report)

    for domain, domain_reports in by_domain.items():
        name = _("Tableau de bord — %(domain)s") % {"domain": domain}
        if BiDashboard.objects.filter(tenant=tenant, name=name).exists():
            continue
        dashboard = BiDashboard.objects.create(
            tenant=tenant,
            name=str(name),
            owner=user,
            role_code="",
            is_shared=True,
            tiles=[
                {"report_id": str(report.id), "position": index, "size": "md"}
                for index, report in enumerate(domain_reports[:6])
            ],
            created_by=user,
        )
        created.append(dashboard)
    return created
