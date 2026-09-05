"""Service du portail externe invite (PJ14) — cf. plan, section « Module
`projects` », etape PJ14. Donne acces a une vue LECTURE SEULE d'un projet a
un tiers externe (client, partenaire) qui n'a et n'aura JAMAIS de compte
`core.User`, de session Django, ni de JWT — l'unique credential est la
possession du `token` (`PrjGuestAccess`, cf. sa docstring pour le detail du
modele de donnees et de la derogation RLS `RLS_FORCE_FOR_OWNER = False`).

**Le probleme de la poule et de l'oeuf, et comment ce module le resout** :
toute lecture normale de ce depot passe par un tenant DEJA connu (session
web via `TenantMiddleware`, ou JWT via l'API django-ninja) — mais un
visiteur invite n'a ni l'un ni l'autre. Le token qu'il possede EST le
tenant (indirectement, via la ligne `PrjGuestAccess` qu'il designe) : il
faut donc pouvoir retrouver CETTE ligne precise AVANT de savoir dans quel
tenant chercher quoi que ce soit d'autre.
`resolve_guest_access` est la SEULE fonction de ce depot autorisee a
interroger une table tenant-scopee sans qu'aucun tenant ne soit actif :
elle utilise `PrjGuestAccess.all_objects` (le manager non filtre fourni
par `BaseModel`, cf. sa docstring) — necessaire mais PAS suffisant a lui
seul, car la Row-Level Security PostgreSQL (`apps.core.management.
commands.apply_rls`) s'applique normalement independamment du manager
Django utilise. `PrjGuestAccess` porte donc en plus `RLS_FORCE_FOR_OWNER
= False` (derogation generique disclosee dans `apply_rls`), qui permet
concretement au role de connexion Django (proprietaire de la table) de
retrouver la ligne par son `token` meme quand `app.tenant_id` n'est pas
positionne. **Cette derogation ne s'applique qu'a CETTE table** : toutes
les autres tables du depot (`PrjProject`, `PrjTask`, `PrjBudgetLine`...)
restent en `FORCE ROW LEVEL SECURITY` standard — c'est pourquoi, une fois
le tenant identifie a partir de la ligne `PrjGuestAccess` trouvee, TOUTE
lecture ulterieure (projet, taches, Gantt) doit explicitement rouvrir un
contexte tenant via `apps.core.tenant_context.activate_tenant(tenant_id)`
avant de continuer — cf. `get_guest_project_view` et la vue appelante
(`apps.projects.views.guest_project_view`).

**Rejet indiscernable des 3 cas d'echec** (token inconnu / revoque /
expire) : `resolve_guest_access` renvoie `None` dans les 3 cas, JAMAIS une
exception, et ne journalise/n'expose aucune information permettant de
distinguer un cas de l'autre cote appelant — la vue HTTP doit renvoyer
exactement la meme reponse 404 generique dans les 3 cas (cf. tests de
`apps/projects/tests/test_guest_portal.py`).

**Ce que ce portail n'expose JAMAIS (decision produit disclosee)** : aucun
montant sensible de marge/cout interne. `get_guest_project_view` reutilise
`services/gantt.py::render_gantt_svg` tel quel (deja sans donnee monetaire)
mais N'APPELLE JAMAIS `services/evm.py::compute_evm_snapshot` ni aucune
lecture de `PrjBudgetLine` — le seul indicateur d'avancement fourni est un
pourcentage d'avancement TACHE (moyenne de `PrjTask.percent_complete`,
donnee de planning, jamais financiere), explicitement documente comme
substitut non-financier a un "resume budgetaire" pour rester strictement
en-deca de la consigne "jamais les montants sensibles de marge/cout
interne" — plus simple et plus sur qu'un ratio derive (ex. AC/BAC) qui,
meme sans exposer un montant absolu, resterait CALCULE a partir de couts
internes. Les taches exposees ne portent que les champs de planning
(reference, type, etat, dates, `percent_complete`) — jamais
`budgeted_amount` (montant contractuel de facturation par jalon,
sensible) ni `custom_fields` (contenu libre non audite pour ce public)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, TypedDict

from django.utils import timezone

from apps.core.models.user import User
from apps.projects.models import PrjGuestAccess, PrjProject, PrjTask
from apps.projects.services.gantt import render_gantt_svg

_TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """Empreinte stockee en base a la place du jeton (L15).

    SHA-256 nu : le jeton porte 256 bits d'entropie cryptographique, il n'y
    a donc ni dictionnaire ni table arc-en-ciel a lui opposer — le sel et le
    cout calculatoire d'un `argon2` protegent contre la faible entropie d'un
    mot de passe humain, absente ici, et rendraient chaque ouverture de lien
    mesurablement plus couteuse. Deterministe A DESSEIN : c'est ce qui
    permet la recherche par valeur que `EncryptedCharField` (Fernet, non
    deterministe) rendrait impossible."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class GuestTaskRow(TypedDict):
    id: str
    reference: str
    task_type: str
    task_type_display: str
    state: str
    state_display: str
    start_date: Any
    end_date: Any
    percent_complete: int


class GuestProjectView(TypedDict):
    project_name: str
    project_description: str
    project_reference: str
    project_status_display: str
    start_date: Any
    end_date: Any
    tasks: list[GuestTaskRow]
    milestones: list[GuestTaskRow]
    gantt_svg: str
    overall_progress_percent: int | None


def create_guest_access(
    project: PrjProject,
    *,
    guest_email: str,
    expires_at: datetime,
    created_by: User | None = None,
) -> PrjGuestAccess:
    """Cree un nouveau lien d'acces invite pour `project`. Le jeton est
    TOUJOURS genere ici (jamais fourni par l'appelant) via
    `secrets.token_urlsafe(32)` — module standard dedie aux jetons de
    securite (32 octets d'entropie cryptographique), jamais un UUID4 seul
    ni `random`, cf. docstring de `PrjGuestAccess`.

    **Le jeton en clair n'est renvoye qu'ici, et une seule fois** (L15) :
    la ligne ne porte que son empreinte, il est donc impossible de le
    retrouver ensuite. L'instance renvoyee porte `plaintext_token`, un
    attribut TRANSITOIRE (jamais un champ, jamais persiste) que l'appelant
    doit consommer immediatement pour construire le lien remis a l'invite.
    Perdu ce lien, il faut en creer un autre — c'est la contrepartie
    assumee, et la meme que celle de toute cle d'API affichee une fois."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    guest_access = PrjGuestAccess.objects.create(
        tenant=project.tenant,
        project=project,
        token_hash=hash_token(token),
        guest_email=guest_email,
        expires_at=expires_at,
        created_by=created_by,
    )
    guest_access.plaintext_token = token
    return guest_access


def revoke_guest_access(guest_access: PrjGuestAccess) -> None:
    """Revoque immediatement un lien d'acces invite avant son echeance
    naturelle. Idempotent : revoquer un acces deja revoque n'est jamais une
    erreur (ne re-ecrase pas `revoked_at`, conserve l'horodatage de la
    PREMIERE revocation)."""
    if guest_access.revoked_at is not None:
        return
    guest_access.revoked_at = timezone.now()
    guest_access.save(update_fields=["revoked_at"])


def resolve_guest_access(token: str) -> PrjGuestAccess | None:
    """Resout un token de portail invite SANS qu'aucun tenant ne soit
    prealablement connu — cf. docstring de module pour le mecanisme complet
    (manager `all_objects` + derogation RLS `RLS_FORCE_FOR_OWNER=False`
    portee par `PrjGuestAccess`). Renvoie `None`, JAMAIS une exception, pour
    les 3 cas : token introuvable, revoque, ou expire — le cote appelant ne
    doit RIEN pouvoir distinguer entre ces 3 cas (meme reponse 404
    generique cote vue)."""
    if not token:
        return None
    guest_access = PrjGuestAccess.all_objects.filter(token_hash=hash_token(token)).first()
    if guest_access is None:
        return None
    if guest_access.revoked_at is not None:
        return None
    if guest_access.expires_at <= timezone.now():
        return None
    return guest_access


def get_guest_project_view(guest_access: PrjGuestAccess) -> GuestProjectView:
    """Construit les donnees LECTURE SEULE du portail invite. **Doit etre
    appelee a l'interieur d'un `apps.core.tenant_context.activate_tenant
    (guest_access.tenant_id)`** — cf. docstring de module ; cette fonction
    elle-meme n'active aucun contexte tenant (separation explicite entre
    "resoudre le token" et "lire les donnees du tenant resolu", cf. la vue
    appelante `apps.projects.views.guest_project_view`).

    N'expose JAMAIS : `PrjTask.budgeted_amount`/`custom_fields`, ni
    aucune donnee de `PrjBudgetLine`/`services/evm.py` (SPI/CPI/AC/EAC) —
    cf. docstring de module pour la justification produit de cette
    exclusion."""
    project = PrjProject.objects.get(id=guest_access.project_id)
    tasks_qs = project.tasks.filter(is_active=True).order_by("start_date", "created_at")

    def _row(task: PrjTask) -> GuestTaskRow:
        return {
            "id": str(task.id),
            "reference": task.reference,
            "task_type": task.task_type,
            "task_type_display": task.get_task_type_display(),
            "state": task.state,
            "state_display": task.get_state_display(),
            "start_date": task.start_date,
            "end_date": task.end_date,
            "percent_complete": task.percent_complete,
        }

    tasks = [_row(t) for t in tasks_qs]
    milestones = [row for row in tasks if row["task_type"] == PrjTask.TYPE_MILESTONE]

    overall_progress_percent: int | None = None
    if tasks:
        overall_progress_percent = round(sum(row["percent_complete"] for row in tasks) / len(tasks))

    return {
        "project_name": project.name,
        "project_description": project.description,
        "project_reference": project.reference,
        "project_status_display": project.get_status_display(),
        "start_date": project.start_date,
        "end_date": project.end_date,
        "tasks": tasks,
        "milestones": milestones,
        "gantt_svg": render_gantt_svg(project),
        "overall_progress_percent": overall_progress_percent,
    }
