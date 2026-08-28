"""PR3 : PRS-ORG1 (organigramme dynamique) — genere un SVG depuis
`PrsEmployee.manager` (aucun modele dedie, cf. CDC "Adapter"). Rendu
minimal (rectangles + traits), suffisant pour un affichage web leger
(coherent avec la contrainte reseau malgache — pas de librairie de
graphes cote client)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from apps.presence.models import PrsEmployee

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

NODE_WIDTH = 180
NODE_HEIGHT = 50
H_GAP = 20
V_GAP = 60


@dataclass
class _OrgNode:
    employee: PrsEmployee
    children: list[_OrgNode] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0


def _build_tree(tenant: Tenant) -> list[_OrgNode]:
    employees = list(
        PrsEmployee.objects.filter(tenant=tenant, is_active=True).select_related("manager")
    )
    nodes = {employee.id: _OrgNode(employee=employee) for employee in employees}
    roots: list[_OrgNode] = []
    for employee in employees:
        node = nodes[employee.id]
        if employee.manager_id and employee.manager_id in nodes:
            nodes[employee.manager_id].children.append(node)
        else:
            roots.append(node)
    return roots


def _layout(node: _OrgNode, depth: int, next_x: list[float]) -> None:
    if not node.children:
        node.x = next_x[0]
        next_x[0] += NODE_WIDTH + H_GAP
    else:
        for child in node.children:
            _layout(child, depth + 1, next_x)
        first, last = node.children[0], node.children[-1]
        node.x = (first.x + last.x) / 2
    node.y = depth * (NODE_HEIGHT + V_GAP)


def _render_node(node: _OrgNode, parts: list[str]) -> None:
    label = escape(f"{node.employee.first_name} {node.employee.last_name}".strip())
    job_title = escape(node.employee.job_title or "")
    parts.append(
        f'<g><rect x="{node.x:.1f}" y="{node.y:.1f}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" '
        'rx="6" fill="#eef2ff" stroke="#4338ca"/>'
        f'<text x="{node.x + NODE_WIDTH / 2:.1f}" y="{node.y + 20:.1f}" '
        'text-anchor="middle" font-size="12" font-weight="bold">'
        f"{label}</text>"
        f'<text x="{node.x + NODE_WIDTH / 2:.1f}" y="{node.y + 38:.1f}" '
        f'text-anchor="middle" font-size="10">{job_title}</text></g>'
    )
    for child in node.children:
        parts.append(
            f'<line x1="{node.x + NODE_WIDTH / 2:.1f}" y1="{node.y + NODE_HEIGHT:.1f}" '
            f'x2="{child.x + NODE_WIDTH / 2:.1f}" y2="{child.y:.1f}" stroke="#94a3b8"/>'
        )
        _render_node(child, parts)


def render_org_chart_svg(tenant: Tenant) -> str:
    """Retourne un document SVG complet — jamais une exception, meme sans
    aucun employe (SVG vide valide)."""
    roots = _build_tree(tenant)
    next_x = [0.0]
    for root in roots:
        _layout(root, depth=0, next_x=next_x)
        next_x[0] += NODE_WIDTH  # separation entre arbres racines distincts

    parts: list[str] = []
    for root in roots:
        _render_node(root, parts)

    max_x = max((next_x[0], NODE_WIDTH))
    max_depth = _max_depth(roots)
    height = (max_depth + 1) * (NODE_HEIGHT + V_GAP)
    body = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{max_x:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {max_x:.0f} {height:.0f}">{body}</svg>'
    )


def _max_depth(nodes: list[_OrgNode]) -> int:
    if not nodes:
        return 0
    return max((1 + _max_depth(node.children) if node.children else 0) for node in nodes)
