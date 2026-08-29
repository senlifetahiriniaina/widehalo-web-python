"""§5.11 reporting : enregistrement des rapports `projects` (PJ15, dernier
jalon du chantier) dans le registre partage `core.services.reports_
registry`, appele depuis `apps.py::ready()` — meme patron que
`apps.strategy.services.reports_registration`/`apps.mrp.services.
reports_registration`. Aucune reimplementation de logique metier ici :
chaque adaptateur se contente de resoudre les objets a partir des
`params` bruts puis de deleguer a une fonction deja existante de
`apps/projects/services/`.

**`PRJ-GANTT`** : le Gantt du projet (`services/gantt.py::
render_gantt_svg`) produit un fragment SVG, PAS un document PDF composite
— a la difference de `MRP-OF`/`STRATEGY-BP` (documents `render_pdf`-only
enveloppant du HTML WeasyPrint). Envelopper ce SVG dans un PDF minimal
serait une couche supplementaire (HTML wrapper + WeasyPrint) pour un
gain limite : le rendu SVG lui-meme reste deja consultable directement
depuis l'ecran `projects/gantt.html` (PJ2). **Choix retenu, disclosed** :
`PRJ-GANTT` est enregistre `render_rows`-only — une ligne par tache
active du projet (reference/type/dates/etat/avancement/chemin critique),
exploitable en PDF/XLSX/CSV/JSON par le moteur generique — meme patron
que `CAP-90J`/`MRP-CRA` (rapport tabulaire simple, pas un document
composite). Le rendu SVG interactif reste, lui, servi par l'ecran HTMX
existant, jamais duplique ici.

**`PRJ-EVM`** : instantane EVM (PV/EV/AC/BAC/SPI/CPI/EAC) du projet,
`render_rows`-only (une seule ligne) — reutilise `services/evm.py::
compute_evm_snapshot` telle quelle, AUCUNE reimplementation du calcul.

**`PRJ-STATUS`** : rapport d'etat de projet **deterministe** (pas de
prose IA) — a dessein DIFFERENT de `services/ai_assistant.py::
generate_status_report` (PJ12, synthese en prose eventuellement assistee
par LLM). Un rapport du catalogue generique doit produire un resultat
IDENTIQUE et systematique quel que soit l'etat de la configuration IA du
tenant (`settings.AI_PROVIDER_CONFIG` absent ou non) — le faire dependre
de `get_ai_provider()` romprait cette garantie (un rapport qui echouerait
ou degraderait silencieusement selon une configuration externe optionnelle
serait un mauvais candidat de catalogue). `PRJ-STATUS` est donc un
document PDF composite (`render_pdf`-only, meme patron que `STRATEGY-BP`/
`MRP-OF` : HTML minimal enveloppe par WeasyPrint) assemble a partir de
DONNEES DEJA CALCULEES : en-tete projet, ligne budgetaire (BAC/AC),
instantane EVM (`compute_evm_snapshot`) et repartition des taches par
etat — zero recalcul, zero appel LLM."""

from __future__ import annotations

from typing import Any

from django.db.models import Count

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_gantt_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    del actor  # non utilise : la portee est deja le projet cible, pas l'acteur (N3)
    from apps.projects.models import PrjProject

    project = PrjProject.objects.get(id=params["project_id"])
    tasks = project.tasks.filter(is_active=True).order_by("start_date", "created_at")
    return [
        {
            "reference": task.reference or str(task.id),
            "task_type": task.get_task_type_display(),
            "start_date": task.start_date,
            "end_date": task.end_date,
            "state": task.get_state_display(),
            "percent_complete": task.percent_complete,
            "is_critical_path": task.is_critical_path,
        }
        for task in tasks
    ]


def _adapter_evm_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    del actor  # idem : le scoping est le projet cible, pas l'acteur
    from apps.projects.models import PrjProject
    from apps.projects.services.evm import compute_evm_snapshot

    project = PrjProject.objects.get(id=params["project_id"])
    snapshot = compute_evm_snapshot(project)
    return [
        {
            "pv": snapshot.pv,
            "ev": snapshot.ev,
            "ac": snapshot.ac,
            "bac": snapshot.bac,
            "spi": snapshot.spi,
            "cpi": snapshot.cpi,
            "eac": snapshot.eac,
        }
    ]


def _adapter_status_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor  # idem : le scoping est le projet cible, pas l'acteur
    from weasyprint import HTML

    from apps.projects.models import PrjProject, PrjTask
    from apps.projects.services.evm import compute_evm_snapshot

    project = PrjProject.objects.get(id=params["project_id"])
    snapshot = compute_evm_snapshot(project)

    def _fmt(value: Any) -> str:
        return "-" if value is None else str(value)

    tasks_by_state = (
        project.tasks.filter(is_active=True)
        .values("state")
        .annotate(count=Count("id"))
        .order_by("state")
    )
    state_labels = dict(PrjTask.STATE_CHOICES)
    state_rows_html = "".join(
        f"<tr><td>{state_labels.get(row['state'], row['state'])}</td><td>{row['count']}</td></tr>"
        for row in tasks_by_state
    )

    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Rapport d'etat de projet / Project status report — {project.name}</h1>
      <p>Reference : {project.reference}</p>
      <p>Methodologie / Methodology : {project.get_methodology_display()}</p>
      <p>Statut / Status : {project.get_status_display()}</p>
      <p>Debut / Start : {project.start_date or "-"} — Fin / End : {project.end_date or "-"}</p>

      <h2>Sante budgetaire (EVM) / Budget health</h2>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>PV</th><th>EV</th><th>AC</th><th>BAC</th>
          <th>SPI</th><th>CPI</th><th>EAC</th></tr></thead>
        <tbody><tr>
          <td>{_fmt(snapshot.pv)}</td><td>{_fmt(snapshot.ev)}</td>
          <td>{_fmt(snapshot.ac)}</td><td>{_fmt(snapshot.bac)}</td>
          <td>{_fmt(snapshot.spi)}</td><td>{_fmt(snapshot.cpi)}</td>
          <td>{_fmt(snapshot.eac)}</td>
        </tr></tbody>
      </table>

      <h2>Repartition des taches par etat / Tasks by state</h2>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Etat / State</th><th>Nombre / Count</th></tr></thead>
        <tbody>{state_rows_html}</tbody>
      </table>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result


def register_reports() -> None:
    register_report(
        code="PRJ-GANTT",
        module="projects",
        label="Gantt (liste des taches)",
        permission="projects.view_prjproject",
        render_rows=_adapter_gantt_rows,
        fields=(
            "reference",
            "task_type",
            "start_date",
            "end_date",
            "state",
            "percent_complete",
            "is_critical_path",
        ),
    )
    register_report(
        code="PRJ-EVM",
        module="projects",
        label="Valeur acquise (EVM)",
        permission="projects.view_prjproject",
        render_rows=_adapter_evm_rows,
        fields=("pv", "ev", "ac", "bac", "spi", "cpi", "eac"),
    )
    register_report(
        code="PRJ-STATUS",
        module="projects",
        label="Rapport d'etat de projet",
        permission="projects.view_prjproject",
        render_pdf=_adapter_status_pdf,
    )
