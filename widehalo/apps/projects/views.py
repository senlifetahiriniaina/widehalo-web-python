"""Ecrans HTMX minimaux du module `projects` (PJ1) : liste/creation/detail
de projet, ajout de tache et transitions FSM depuis le detail. Meme patron
que `apps.financing.views`/`apps.feasibility.views` : chaque vue appelle
directement les fonctions de service, jamais l'API ninja. Les vues
riches (Gantt SVG, Kanban, EVM...) arrivent aux etapes PJ2+."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tenant_context import activate_tenant
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.projects.models import (
    PrjBudgetLine,
    PrjGuestAccess,
    PrjInvoicingRecord,
    PrjProject,
    PrjSprint,
    PrjTask,
    PrjTeamMember,
    PrjTimeEntry,
    PrjWikiPage,
)
from apps.projects.services.billing import (
    bill_by_milestone,
    bill_by_percentage,
    bill_fixed,
    bill_time_and_material,
)
from apps.projects.services.capacity import (
    add_team_member,
    compute_project_capacity_summary,
    compute_user_workload_heatmap,
    remove_team_member,
)
from apps.projects.services.evm import (
    add_budget_line,
    compute_evm_snapshot,
    compute_s_curve,
    refresh_project_health,
)
from apps.projects.services.gantt import compute_critical_path, render_gantt_svg
from apps.projects.services.guest_portal import (
    create_guest_access,
    get_guest_project_view,
    resolve_guest_access,
    revoke_guest_access,
)
from apps.projects.services.projects import create_project
from apps.projects.services.public import get_linked_objective_summary, link_project_to_objective
from apps.projects.services.sprints import (
    complete_sprint,
    compute_burndown,
    compute_velocity,
    create_sprint,
    get_backlog,
    start_sprint,
)
from apps.projects.services.tasks import (
    block_task,
    cancel_task,
    create_task,
    finish_task,
    start_task,
    unblock_task,
)
from apps.projects.services.time_tracking import get_time_report, start_timer, stop_timer
from apps.projects.services.wiki import (
    attach_document_to_project,
    attach_document_to_wiki_page,
    create_wiki_page,
    list_documents_for,
    list_wiki_pages,
    update_wiki_page,
)

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="methodology", label="Methodologie", searchable=False),
    Column(key="status", label="Statut", searchable=False),
]

_TASK_TRANSITIONS = {
    "start": start_task,
    "block": block_task,
    "unblock": unblock_task,
    "finish": finish_task,
    "cancel": cancel_task,
}


@login_required
def project_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    queryset = PrjProject.objects.filter(tenant=tenant, is_active=True)
    return smart_table_response(
        request,
        table_key="projects.projects",
        columns=COLUMNS,
        queryset=queryset,
        page_template="projects/list.html",
        page_context={"row_url_name": "projects:detail"},
    )


@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None
    if request.method == "POST":
        try:
            project = create_project(
                tenant,
                name=request.POST.get("name", ""),
                description=request.POST.get("description", ""),
                methodology=request.POST.get("methodology", PrjProject.METHODOLOGY_WATERFALL),
                owner=cast(User, request.user),
            )
            return redirect("projects:detail", project_id=project.id)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
    return render(
        request,
        "projects/create.html",
        {"error": error, "methodologies": PrjProject.METHODOLOGY_CHOICES},
    )


@login_required
def project_detail(request: HttpRequest, project_id: str) -> HttpResponse:
    """**PJ8** : bouton demarrer/arrete le chrono directement depuis cette
    liste de taches (aucun ecran de detail tache dedie n'existe encore dans
    ce depot, cf. plan) — `action=start_timer`/`stop_timer`. `stop_timer`
    resout le chrono en cours de L'UTILISATEUR COURANT sur cette tache
    (`user=request.user, stopped_at__isnull=True`) : un utilisateur ne voit
    jamais le chrono d'un collegue depuis cet ecran, `services/time_
    tracking.py::stop_timer` re-verifie de toute facon la propriete cote
    service (defense en profondeur)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        user = cast(User, request.user)
        try:
            if action == "add_task":
                parent_id = request.POST.get("parent_id") or None
                parent = (
                    get_object_or_404(PrjTask, id=parent_id, project=project) if parent_id else None
                )
                create_task(
                    project.tenant,
                    project=project,
                    task_type=request.POST.get("task_type", PrjTask.TYPE_TASK),
                    parent=parent,
                )
            elif action == "start_timer":
                task_id = request.POST.get("task_id", "")
                task = get_object_or_404(PrjTask, id=task_id, project=project)
                start_timer(task, user)
            elif action == "stop_timer":
                task_id = request.POST.get("task_id", "")
                task = get_object_or_404(PrjTask, id=task_id, project=project)
                time_entry = get_object_or_404(
                    PrjTimeEntry, task=task, user=user, stopped_at__isnull=True
                )
                stop_timer(time_entry, user)
            elif action == "link_objective":
                # PJ13 : champ vide -> deliaison explicite (`None`), meme
                # discipline que `services/public.py::
                # link_project_to_objective`.
                objective_id = request.POST.get("objective_id", "").strip() or None
                link_project_to_objective(project, objective_id)
            else:
                task_id = request.POST.get("task_id", "")
                task = get_object_or_404(PrjTask, id=task_id, project=project)
                transition_fn = _TASK_TRANSITIONS.get(action or "")
                if transition_fn is not None:
                    transition_fn(task, user)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
        except TransitionPermissionError as exc:
            error = str(exc)

    tasks = project.tasks.filter(is_active=True)
    running_task_ids = set(
        PrjTimeEntry.objects.filter(
            task__project=project, user=cast(User, request.user), stopped_at__isnull=True
        ).values_list("task_id", flat=True)
    )
    # PJ13 : widget KPI — EVM propre au projet (donnee deja calculee par
    # PJ4, jamais recalculee ici) + resume de l'objectif strategique lie
    # (`None` si non lie ou reference perimee/etrangere, cf. `services/
    # public.py::get_linked_objective_summary`).
    evm_snapshot = compute_evm_snapshot(project)
    linked_objective = get_linked_objective_summary(project)
    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "tasks": tasks,
            "task_types": PrjTask.TYPE_CHOICES,
            "running_task_ids": running_task_ids,
            "evm_snapshot": evm_snapshot,
            "linked_objective": linked_objective,
            "error": error,
        },
    )


@login_required
def project_gantt(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran Gantt (PJ2) : rendu SVG serveur (`render_gantt_svg`) +
    formulaire HTMX classique de modification des dates d'une tache, qui
    poste vers cette meme vue (pas encore un "drag" visuel en JS — cf.
    disclosure de `services/gantt.py`, l'amelioration interactive reelle
    est reportee ; l'API `PATCH /api/v1/projects/tasks/{id}/gantt`
    equivalente est deja disponible pour un futur client JS)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        task_id = request.POST.get("task_id", "")
        task = get_object_or_404(PrjTask, id=task_id, project=project)
        try:
            update_fields = []
            start_date = request.POST.get("start_date") or ""
            end_date = request.POST.get("end_date") or ""
            duration_days = request.POST.get("duration_days") or ""
            if start_date:
                task.start_date = dt.date.fromisoformat(start_date)
                update_fields.append("start_date")
            if end_date:
                task.end_date = dt.date.fromisoformat(end_date)
                update_fields.append("end_date")
            if duration_days:
                task.duration_days = int(duration_days)
                update_fields.append("duration_days")
            if update_fields:
                task.save(update_fields=update_fields)
            compute_critical_path(project)
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    tasks = project.tasks.filter(is_active=True)
    gantt_svg = render_gantt_svg(project)
    return render(
        request,
        "projects/gantt.html",
        {
            "project": project,
            "tasks": tasks,
            # `render_gantt_svg` echappe (`html.escape`) chaque fragment
            # texte interpole (reference/nom de tache) avant assemblage —
            # `mark_safe` est donc sur une chaine deja assainie, pas sur
            # une entree utilisateur brute.
            "gantt_svg": mark_safe(gantt_svg),  # noqa: S308
            "error": error,
        },
    )


@login_required
def project_budget(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran budget/EVM (PJ4) : tableau des lignes budgetaires + indicateurs
    SPI/CPI/EAC — cf. `services/evm.py`. **Pas de graphique reel de la
    courbe en S** (disclosed explicitement, cf. docstring de module de
    `services/evm.py`) : `compute_s_curve` alimente ici une simple table de
    valeurs cumulees. **Decision de cloture PJ15** : un rendu graphique
    dedie (SVG/JS) de cette courbe reste une simplification V1 assumee,
    definitivement pas construite dans ce chantier — les donnees restent
    disponibles (`compute_s_curve`) pour un futur module de visualisation,
    mais le catalogue de rapports PJ15 (`PRJ-GANTT`/`PRJ-EVM`/`PRJ-STATUS`,
    cf. `services/reports_registration.py`) ne l'inclut pas non plus (hors
    perimetre disclosed, cf. rapport de cloture)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        try:
            add_budget_line(
                project,
                category=request.POST.get("category", PrjBudgetLine.CATEGORY_OPEX),
                label=request.POST.get("label", ""),
                planned_amount=Decimal(request.POST.get("planned_amount") or "0"),
                actual_amount=Decimal(request.POST.get("actual_amount") or "0"),
                period=dt.date.fromisoformat(request.POST.get("period", "")),
            )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    snapshot = refresh_project_health(project)
    lines = project.budget_lines.filter(is_active=True)
    s_curve = compute_s_curve(project)
    return render(
        request,
        "projects/budget.html",
        {
            "project": project,
            "lines": lines,
            "snapshot": snapshot,
            "s_curve": s_curve,
            "categories": PrjBudgetLine.CATEGORY_CHOICES,
            "error": error,
        },
    )


@login_required
def project_billing(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran HTMX minimal de facturation multi-modes (PJ5) — cf.
    `services/billing.py`. **RBAC** : meme discipline que le reste des
    ecrans HTMX de ce module (`accounting.views`/`purchase.views`, cf.
    disclosure de ces fichiers) — le controle N2 fin
    (`projects.bill_prjproject`, restreint a `admin`/`direction`/
    `resp_commercial`) est applique cote API django-ninja
    (`apps.projects.api`) ; cet ecran, comme tous les ecrans HTMX de ce
    depot, ne fait que `@login_required` (le menu/lien n'est de toute facon
    affiche qu'aux roles concernes dans la pratique reelle du produit, pas
    encore cable au niveau template a ce stade)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    success = None

    if request.method == "POST":
        mode = request.POST.get("mode", "")
        user = cast(User, request.user)
        try:
            if mode == PrjInvoicingRecord.MODE_MILESTONE:
                task_id = request.POST.get("task_id", "")
                task = get_object_or_404(PrjTask, id=task_id, project=project)
                invoice_id = bill_by_milestone(project, task, user)
            elif mode == PrjInvoicingRecord.MODE_PERCENTAGE:
                invoice_id = bill_by_percentage(project, user)
            elif mode == PrjInvoicingRecord.MODE_TIME_AND_MATERIAL:
                hourly_rate = Decimal(request.POST.get("hourly_rate") or "0")
                invoice_id = bill_time_and_material(project, user, hourly_rate=hourly_rate)
            elif mode == PrjInvoicingRecord.MODE_FIXED:
                amount = Decimal(request.POST.get("amount") or "0")
                invoice_id = bill_fixed(project, user, amount=amount)
            else:
                error = str(_("Mode de facturation inconnu."))
                invoice_id = None
            if invoice_id is not None:
                success = _("Facture creee (brouillon, a valider dans le module Comptabilite).")
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    records = project.invoicing_records.filter(is_active=True)
    billable_milestones = project.tasks.filter(
        task_type=PrjTask.TYPE_MILESTONE, state=PrjTask.STATE_DONE, is_active=True
    )
    return render(
        request,
        "projects/billing.html",
        {
            "project": project,
            "records": records,
            "billable_milestones": billable_milestones,
            "modes": PrjInvoicingRecord.MODE_CHOICES,
            "error": error,
            "success": success,
        },
    )


@login_required
def project_sprints(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran HTMX minimal de gestion des sprints (PJ6) : creation, demarrage
    et cloture — meme discipline "chaque vue appelle directement les
    fonctions de service" que le reste du module (cf. docstring de module
    ci-dessus)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create":
                create_sprint(
                    project,
                    name=request.POST.get("name", ""),
                    start_date=dt.date.fromisoformat(request.POST.get("start_date", "")),
                    end_date=dt.date.fromisoformat(request.POST.get("end_date", "")),
                    goal=request.POST.get("goal", ""),
                )
            else:
                sprint_id = request.POST.get("sprint_id", "")
                sprint = get_object_or_404(PrjSprint, id=sprint_id, project=project)
                if action == "start":
                    start_sprint(sprint)
                elif action == "complete":
                    complete_sprint(sprint)
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    sprints = project.sprints.filter(is_active=True)
    velocity = compute_velocity(project)
    return render(
        request,
        "projects/sprints.html",
        {"project": project, "sprints": sprints, "velocity": velocity, "error": error},
    )


@login_required
def project_backlog(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran backlog (PJ6) : taches du projet sans sprint assigne, hors
    `cancelled`/`done` — cf. `services/sprints.py::get_backlog`."""
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = get_backlog(project)
    return render(request, "projects/backlog.html", {"project": project, "tasks": tasks})


@login_required
def project_kanban(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran Kanban en lecture seule (PJ6) : taches du projet groupees par
    colonne `state` (todo/in_progress/blocked/done) — reutilise les
    donnees existantes (`PrjTask.state`), aucun nouveau modele. Meme
    patron visuel simple (tables/listes brutes) que le reste des ecrans
    HTMX de ce module (cf. `projects/detail.html`) — pas de nouveau
    CSS/JS de glisser-deposer, disclosed comme simplifie (lecture seule ;
    le changement d'etat d'une tache reste pilote depuis l'ecran detail/
    l'API `transition`)."""
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = project.tasks.filter(is_active=True)
    columns = [(state, label, tasks.filter(state=state)) for state, label in PrjTask.STATE_CHOICES]
    return render(request, "projects/kanban.html", {"project": project, "columns": columns})


@login_required
def project_calendar(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran calendrier en lecture seule (PJ6), **volontairement simplifie**
    (disclosed) : pas de vrai widget de calendrier riche (grille
    mensuelle interactive) — une liste des taches ayant une `start_date`
    groupees par mois calendaire suffit au besoin exprime ("vue simple").
    Une tache sans `start_date` n'apparait dans aucun mois (rien
    d'invente)."""
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = project.tasks.filter(is_active=True, start_date__isnull=False).order_by("start_date")
    months: dict[str, list[PrjTask]] = {}
    for task in tasks:
        assert task.start_date is not None  # garanti par le filtre ci-dessus
        key = task.start_date.strftime("%Y-%m")
        months.setdefault(key, []).append(task)
    return render(
        request,
        "projects/calendar.html",
        {"project": project, "months": sorted(months.items())},
    )


@login_required
def project_roadmap(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran roadmap en lecture seule (PJ6) : vue chronologique haut niveau
    des taches de type `epic`/`milestone` du projet (les 2 `task_type` de
    plus haut niveau de la hierarchie unifiee, cf. docstring de `PrjTask`),
    triees par date (`start_date` si renseignee, sinon `end_date`, sinon en
    dernier — jamais une date inventee)."""
    project = get_object_or_404(PrjProject, id=project_id)
    tasks = project.tasks.filter(
        is_active=True, task_type__in=[PrjTask.TYPE_EPIC, PrjTask.TYPE_MILESTONE]
    )
    ordered = sorted(
        tasks, key=lambda t: (t.start_date or t.end_date or dt.date.max, t.start_date is None)
    )
    return render(request, "projects/roadmap.html", {"project": project, "tasks": ordered})


@login_required
def project_sprint_burndown(request: HttpRequest, project_id: str, sprint_id: str) -> HttpResponse:
    """Ecran burndown/velocite (PJ6) — cf. `services/sprints.py::
    compute_burndown`/`compute_velocity` pour la methode retenue et ses
    limitations disclosees (source `StateTransitionLog`)."""
    project = get_object_or_404(PrjProject, id=project_id)
    sprint = get_object_or_404(PrjSprint, id=sprint_id, project=project)
    burndown = compute_burndown(sprint)
    velocity = compute_velocity(project)
    return render(
        request,
        "projects/burndown.html",
        {"project": project, "sprint": sprint, "burndown": burndown, "velocity": velocity},
    )


@login_required
def project_team(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran HTMX minimal de gestion d'equipe (PJ7) : ajout/retrait de
    membres avec allocation — cf. `services/capacity.py::add_team_member`/
    `remove_team_member`. Meme discipline "chaque vue appelle directement
    les fonctions de service" que le reste du module."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        action = request.POST.get("action", "add")
        try:
            if action == "add":
                user = get_object_or_404(User, id=request.POST.get("user_id", ""))
                add_team_member(
                    project,
                    user,
                    role=request.POST.get("role", ""),
                    allocation_pct=int(request.POST.get("allocation_pct") or 0),
                )
            elif action == "remove":
                member = get_object_or_404(
                    PrjTeamMember, id=request.POST.get("member_id", ""), project=project
                )
                remove_team_member(member)
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    summary = compute_project_capacity_summary(project)
    return render(
        request,
        "projects/team.html",
        {"project": project, "summary": summary, "error": error},
    )


@login_required
def project_time_report(request: HttpRequest, project_id: str) -> HttpResponse:
    """Ecran HTMX minimal de rapport de temps par projet (PJ8) — cf.
    `services/time_tracking.py::get_time_report`. Filtre optionnel
    `date_from`/`date_to` (formulaire GET, memes bornes que le service :
    inclusives des deux cotes)."""
    project = get_object_or_404(PrjProject, id=project_id)
    date_from_raw = request.GET.get("date_from") or ""
    date_to_raw = request.GET.get("date_to") or ""
    date_from = dt.date.fromisoformat(date_from_raw) if date_from_raw else None
    date_to = dt.date.fromisoformat(date_to_raw) if date_to_raw else None
    report = get_time_report(project, date_from=date_from, date_to=date_to)
    return render(
        request,
        "projects/time_report.html",
        {
            "project": project,
            "report": report,
            "date_from": date_from_raw,
            "date_to": date_to_raw,
        },
    )


@login_required
def user_capacity_heatmap(request: HttpRequest, user_id: str) -> HttpResponse:
    """Ecran HTMX de heatmap de capacite d'un utilisateur (PJ7) — cf.
    `services/capacity.py::compute_user_workload_heatmap`."""
    user = get_object_or_404(User, id=user_id)
    heatmap = compute_user_workload_heatmap(user)
    return render(
        request,
        "projects/capacity_heatmap.html",
        {"target_user": user, "heatmap": heatmap},
    )


@login_required
def project_risks(request: HttpRequest, project_id: str) -> HttpResponse:
    """PJ9 : matrice de risques filtree par projet — reutilise integralement
    le registre generique `core.RiskItem` (RSK1-2), jamais un registre
    dedie a `projects`. Filtre par `content_type=PrjProject`/`object_id=
    project.id`, categorie CATEGORY_PROJECT par convention (pas une
    contrainte technique : un risque rattache a un `PrjProject` avec une
    autre categorie resterait visible ici, le filtre porte sur le
    rattachement, pas la categorie)."""
    from apps.core.models.risk import RiskItem

    project = get_object_or_404(PrjProject, id=project_id)
    content_type = ContentType.objects.get_for_model(PrjProject)
    risks = RiskItem.objects.filter(content_type=content_type, object_id=str(project.id))
    return render(
        request,
        "projects/risks.html",
        {"project": project, "risks": risks},
    )


@login_required
def project_risk_create(request: HttpRequest, project_id: str) -> HttpResponse:
    """PJ9 : signale un risque rattache a ce projet — appelle directement
    `core.services.risk.create_risk_item(content_object=project, ...)`,
    jamais une duplication du mecanisme de scoring/publication
    `risk.flagged` deja construit a RSK1-2 (regle de couplage n°5)."""
    from apps.core.models.risk import CATEGORY_PROJECT
    from apps.core.services.risk import create_risk_item

    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        user = cast(User, request.user)
        try:
            likelihood = int(request.POST.get("likelihood", "0"))
            impact = int(request.POST.get("impact", "0"))
            if not (1 <= likelihood <= 5) or not (1 <= impact <= 5):
                raise ValueError
        except ValueError:
            error = _("Probabilite et impact doivent etre des entiers entre 1 et 5.")
        else:
            create_risk_item(
                tenant=project.tenant,
                category=CATEGORY_PROJECT,
                likelihood=likelihood,
                impact=impact,
                owner=user,
                mitigation_plan=request.POST.get("mitigation_plan", ""),
                content_object=project,
            )
            return redirect("projects:risks", project_id=project.id)
    return render(
        request,
        "projects/risk_create.html",
        {"project": project, "error": error},
    )


def _wiki_page_rows(project: PrjProject) -> list[tuple[PrjWikiPage, int]]:
    """Aplati la hierarchie de pages en une liste `(page, niveau)` —
    indentation simple par niveau, cf. plan (« pas besoin d'un arbre
    interactif riche »)."""
    rows: list[tuple[PrjWikiPage, int]] = []

    def _walk(page: PrjWikiPage, level: int) -> None:
        rows.append((page, level))
        for child in page.children.filter(is_active=True).order_by("title"):
            _walk(child, level + 1)

    for root in list_wiki_pages(project).order_by("title"):
        _walk(root, 0)
    return rows


@login_required
def project_wiki(request: HttpRequest, project_id: str) -> HttpResponse:
    """PJ10 : liste hierarchique des pages de wiki du projet (indentation
    par niveau) + formulaire de creation d'une nouvelle page (racine ou
    sous-page d'une page existante)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    if request.method == "POST":
        user = cast(User, request.user)
        parent_id = request.POST.get("parent_id") or None
        parent = (
            get_object_or_404(PrjWikiPage, id=parent_id, project=project) if parent_id else None
        )
        try:
            page = create_wiki_page(
                project,
                title=request.POST.get("title", ""),
                body=request.POST.get("body", ""),
                author=user,
                parent=parent,
            )
        except ValidationError as exc:
            error = str(exc)
        else:
            return redirect("projects:wiki_detail", project_id=project.id, page_id=page.id)
    return render(
        request,
        "projects/wiki.html",
        {"project": project, "rows": _wiki_page_rows(project), "error": error},
    )


@login_required
def wiki_page_detail(request: HttpRequest, project_id: str, page_id: str) -> HttpResponse:
    """PJ10 : detail/edition d'une page de wiki + formulaire d'upload de
    document rattache a CETTE page (`services/wiki.py::
    attach_document_to_wiki_page`)."""
    project = get_object_or_404(PrjProject, id=project_id)
    page = get_object_or_404(PrjWikiPage, id=page_id, project=project)
    error = None

    if request.method == "POST":
        user = cast(User, request.user)
        action = request.POST.get("action", "update")
        uploaded_file = request.FILES.get("document")
        if action == "upload_document" and uploaded_file is not None:
            attach_document_to_wiki_page(page, uploaded_file, user)
        else:
            update_wiki_page(
                page,
                title=request.POST.get("title") or None,
                body=request.POST.get("body"),
            )
        return redirect("projects:wiki_detail", project_id=project.id, page_id=page.id)

    documents = list_documents_for(page)
    return render(
        request,
        "projects/wiki_detail.html",
        {"project": project, "page": page, "documents": documents, "error": error},
    )


@login_required
def project_documents(request: HttpRequest, project_id: str) -> HttpResponse:
    """PJ10 : documents rattaches directement au PROJET (pas a une page de
    wiki en particulier) + formulaire d'upload, cf. `services/wiki.py::
    attach_document_to_project`."""
    project = get_object_or_404(PrjProject, id=project_id)
    uploaded_file = request.FILES.get("document")
    if request.method == "POST" and uploaded_file is not None:
        user = cast(User, request.user)
        attach_document_to_project(project, uploaded_file, user)
        return redirect("projects:documents", project_id=project.id)
    documents = list_documents_for(project)
    return render(
        request,
        "projects/documents.html",
        {"project": project, "documents": documents},
    )


@login_required
def project_guest_links(request: HttpRequest, project_id: str) -> HttpResponse:
    """PJ14 : ecran HTMX minimal de gestion des liens de portail invite d'un
    projet (creation/revocation) — cf. `services/guest_portal.py` pour le
    mecanisme de resolution de token. **L'URL complete du lien invite n'est
    affichee qu'UNE SEULE FOIS**, juste apres sa creation (`new_link_url`
    dans le contexte) — la liste des liens existants ci-dessous n'affiche
    plus jamais l'URL/le token en clair, seulement l'email invite/l'echeance
    /le statut, meme discipline "secret affiche une seule fois" qu'un mot de
    passe temporaire genere (cf. `bootstrap_admin`)."""
    project = get_object_or_404(PrjProject, id=project_id)
    error = None
    new_link_url = None
    if request.method == "POST":
        action = request.POST.get("action", "create")
        user = cast(User, request.user)
        try:
            if action == "create":
                expires_at_raw = request.POST.get("expires_at", "")
                expires_at = dt.datetime.fromisoformat(expires_at_raw)
                if timezone.is_naive(expires_at):
                    expires_at = timezone.make_aware(expires_at)
                guest_access = create_guest_access(
                    project,
                    guest_email=request.POST.get("guest_email", ""),
                    expires_at=expires_at,
                    created_by=user,
                )
                new_link_url = request.build_absolute_uri(
                    reverse("projects:guest_view", args=[guest_access.token])
                )
            elif action == "revoke":
                guest_access = get_object_or_404(
                    PrjGuestAccess, id=request.POST.get("guest_access_id", ""), project=project
                )
                revoke_guest_access(guest_access)
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    guest_accesses = project.guest_accesses.filter(is_active=True)
    return render(
        request,
        "projects/guest_links.html",
        {
            "project": project,
            "guest_accesses": guest_accesses,
            "new_link_url": new_link_url,
            "error": error,
        },
    )


@require_GET
def guest_project_view(request: HttpRequest, token: str) -> HttpResponse:
    """PJ14 : portail externe invite — ecran HTML entierement ANONYME,
    jamais de compte `core.User`/session/JWT, gate uniquement par la
    possession du `token` (`services/guest_portal.py::resolve_guest_access`,
    lire sa docstring pour le mecanisme complet de resolution du tenant
    AVANT tout contexte tenant connu). `@require_GET` (pas
    `@login_required`, volontairement hors du cycle `TenantMiddleware`
    normal) : aucune methode d'ecriture n'est exposee a cette URL, un `POST`
    y est rejete par Django lui-meme (405) avant meme d'atteindre cette
    fonction. Les 3 cas d'echec (token introuvable / revoque / expire)
    renvoient EXACTEMENT la meme 404 generique — cf. docstring de
    `resolve_guest_access` pour la justification (ne jamais reveler au
    porteur d'un token invalide LEQUEL des 3 cas s'est produit)."""
    guest_access = resolve_guest_access(token)
    if guest_access is None:
        raise Http404
    with activate_tenant(guest_access.tenant_id):
        view_data = get_guest_project_view(guest_access)
    return render(request, "projects/guest_portal.html", view_data)
