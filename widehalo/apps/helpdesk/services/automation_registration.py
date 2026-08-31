"""AUTO3 (chantier Studio de workflow visuel) : enregistrement de l'action
`helpdesk.create_ticket_from_event` dans le registre partage `core.
services.automation_registry`, appele depuis `apps.py::ready()` — meme
patron que `apps.purchase.services.automation_registration`/`apps.mrp.
services.automation_registration` deja etablis dans ce chantier.

**LE mecanisme concret de « connexion native aux operations »** (cf. plan,
section « Extension actee en cours de route ») : cette action, une fois
enregistree, est declenchable par le Studio de workflow visuel sur
N'IMPORTE QUEL evenement DEJA publie (`risk.flagged`, `ai.anomaly_detected`,
`workflow.transitioned`, `helpdesk.ticket_escalated`, tout futur
`event_type`) SANS aucune modification de `apps.automation` — confirme par
lecture directe de `apps.automation.services.engine` avant d'ecrire ce
fichier : le moteur appelle `core.services.automation_registry.
get_registered_action(action_code)` de facon totalement generique, et
`resolve_param_mapping` evalue chaque parametre soit comme une valeur
statique soit comme une expression `core.services.expr` contre le payload
de l'evenement declencheur — aucun branchement specifique a `helpdesk` a
ajouter cote moteur.

**Resolution du "demandeur" (`HlpTicket.requester`, FK obligatoire) pour un
ticket cree SANS intervention humaine** : ce depot n'a aucun concept
d'"utilisateur systeme". Deux precedents existent deja pour exactement ce
probleme :
1. `apps.helpdesk.services.escalation.run_escalation_checks` (HD2) evite le
   probleme entierement en passant `user=None` a `attempt_transition` — mais
   cela ne fonctionne QUE parce qu'aucune transition FSM de `HlpTicket` ne
   declare de `permission=` (donc `has_transition_perm` n'exige aucun
   utilisateur reel). Ce contournement est INAPPLICABLE ici : `requester`
   n'est pas un parametre de transition FSM, c'est un champ de DONNEES
   obligatoire (`on_delete=PROTECT`), il ne peut pas rester `None`.
2. `apps.purchase.services.reordering.trigger_reordering`/`apps.sales.
   services.recurrence` (via `run_sales_recurrences`) resolvent CE MEME
   probleme (un FK `requester`/`salesperson` obligatoire sans acteur humain
   disponible) en repliant sur **le premier superutilisateur du tenant**
   (`User.objects.filter(is_superuser=True).order_by("id").first()`) —
   `core.User` etant un systeme partage entre tenants, jamais duplique par
   tenant, meme raisonnement documente dans ces deux precedents.

**Cette action reutilise EXACTEMENT la meme strategie que le precedent
n°2** (jamais un second patron invente pour le meme probleme sous-jacent) :
`_resolve_fallback_requester(tenant)` est un mirror direct. Contrairement a
`run_sales_recurrences`/`trigger_reordering` (qui iterent sur TOUS les
tenants et ignorent silencieusement ceux sans superutilisateur), cette
action n'agit que sur UN SEUL tenant a la fois (contrat impose par la
signature uniforme `(tenant_id, params)` du registre) — l'absence de
superutilisateur est donc un echec fatal a CETTE action, remonte comme une
exception normale : `apps.automation.services.engine` capture DEJA toute
exception d'une action tierce (`except Exception` explicite, jamais
propagee au run complet, `AutoRunStep` trace l'echec, le flux continue vers
l'etape suivante) — aucune isolation supplementaire n'est necessaire ici.

**Resolution `content_type_label`/`object_id` -> `content_object` : ne DOIT
JAMAIS faire echouer l'action** (contrairement au cas ci-dessus) — un
`content_type_label` errone/inconnu, un `object_id` introuvable, ou meme
leur absence totale sont des cas ATTENDUS (le payload d'un evenement
declencheur peut ne rien porter de tel, ex. `notification.created`) :
`_resolve_content_object` degrade toujours silencieusement vers `None`,
jamais une exception — meme discipline "isolation des echecs" que `apps.
ai.services.anomaly_detection.run_all_checks`/`apps.ai.services.
automated_insights._collect_deterministic_insights` (une seule source qui
echoue ne doit jamais faire echouer les autres, ici : une seule tentative
de rattachement qui echoue ne doit jamais empecher la creation du ticket
lui-meme). Le pattern de resolution du `content_type_label`
(`ContentType.objects.get_by_natural_key`, capture `ContentType.
DoesNotExist`) est un mirror EXACT de `apps.ai.services.anomaly_detection.
_resolve_content_type` (lu directement avant d'ecrire cette fonction)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from apps.core.services.automation_registry import register_action


def _resolve_content_type(content_type_label: str) -> ContentType | None:
    """Mirror exact de `apps.ai.services.anomaly_detection.
    _resolve_content_type` — `"app_label.modelname"` -> `ContentType`, ou
    `None` si le label est mal forme ou ne designe aucun modele reel
    installe. Jamais une exception."""
    parts = content_type_label.split(".", 1)
    if len(parts) != 2:
        return None
    app_label, model = parts
    try:
        return ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        return None


def _resolve_content_object(params: dict[str, Any]) -> tuple[Any | None, ContentType | None]:
    """Renvoie `(content_object, content_type)` — `(None, None)` pour tout
    echec de resolution (label absent/errone, objet introuvable, tenant
    mismatch...), JAMAIS une exception (cf. docstring de tete de module).
    `content_type` est renvoye separement de `content_object` car il reste
    utile pour la correspondance `ticket_type` (cf. `_create_ticket_from_
    event`) meme quand l'instance elle-meme n'a pas pu etre chargee."""
    content_type_label = params.get("content_type_label")
    object_id = params.get("object_id")
    if not content_type_label or not object_id:
        return None, None

    content_type = _resolve_content_type(content_type_label)
    if content_type is None:
        return None, None

    try:
        model_class = content_type.model_class()
        if model_class is None:
            return None, content_type
        # `type[Model]` n'expose pas `objects` au sens des stubs generiques
        # (limitation connue du plugin django-stubs sur un `Model` resolu
        # dynamiquement via `ContentType.model_class()`, meme contournement
        # que pour tout autre appel arbitraire sur un type resolu au
        # runtime) — sans danger ici, `objects` existe reellement sur tout
        # modele Django concret.
        content_object = model_class.objects.filter(pk=object_id).first()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - jamais laisser une erreur de lookup faire echouer la creation du ticket
        content_object = None

    return content_object, content_type


def _resolve_fallback_requester(tenant_id: str) -> Any:
    """Meme repli EXACT que `apps.purchase.services.reordering.
    trigger_reordering`/`apps.sales.management.commands.
    run_sales_recurrences` pour un FK acteur obligatoire sans utilisateur
    humain disponible (cf. docstring de tete de module, point 2) : le
    premier superutilisateur du tenant (`core.User` est un systeme partage
    entre tenants, jamais duplique par tenant)."""
    del tenant_id  # `core.User` n'est pas duplique par tenant (meme raisonnement que ci-dessus)
    from apps.core.models.user import User

    return User.objects.filter(is_superuser=True).order_by("id").first()


def _create_ticket_from_event(tenant_id: str, params: dict[str, Any]) -> str:
    """Action `helpdesk.create_ticket_from_event` (cf. docstring de tete de
    module pour la justification complete de chaque choix ci-dessous).

    Cree un `HlpTicket` `kind="incident"` a partir d'un evenement
    quelconque du bus (`risk.flagged`/`ai.anomaly_detected`/
    `workflow.transitioned`/tout futur `event_type`), rattache par
    `content_type`/`object_id` a l'entite source quand `params` en porte
    (jamais obligatoire), et resout `ticket_type` par correspondance sur
    `HlpTicketTypeCatalog.related_content_type` — **jamais une supposition
    hasardeuse** : `None` reste le resultat attendu la plupart du temps
    (seules les entrees de la fixture HD1 qui declarent EXACTEMENT ce
    `related_content_type` matchent).

    Renvoie la reference du ticket cree (`str`, meme convention de retour
    "valeur scalaire simple" que `purchase.open_incident`/`mrp.
    open_conformity_incident` — la reference est prefere a l'id technique
    ici car directement lisible dans l'historique d'execution du Studio)."""
    from apps.core.models.tenant import Tenant
    from apps.helpdesk.models import KIND_INCIDENT, HlpTicketTypeCatalog
    from apps.helpdesk.services.tickets import create_ticket

    tenant = Tenant.objects.get(id=tenant_id)

    requester = _resolve_fallback_requester(tenant_id)
    if requester is None:
        # Echec fatal a CETTE action uniquement (cf. docstring de tete de
        # module) : `apps.automation.services.engine` capture deja toute
        # exception d'une action tierce et trace l'echec sans bloquer le
        # reste du flux.
        raise ValueError(
            f"Aucun superutilisateur disponible pour le tenant {tenant_id} : "
            "impossible de resoudre un demandeur pour la creation automatique de ticket."
        )

    subject = params.get("subject") or str(_("Incident détecté automatiquement"))
    description = params.get("description", "")

    content_object, content_type = _resolve_content_object(params)
    ticket_type = None
    if content_type is not None:
        ticket_type = HlpTicketTypeCatalog.objects.filter(
            tenant=tenant, related_content_type=content_type, is_active=True
        ).first()

    ticket = create_ticket(
        tenant,
        subject=subject,
        requester=requester,
        kind=KIND_INCIDENT,
        description=description,
        ticket_type=ticket_type,
        content_object=content_object,
    )
    return ticket.reference or str(ticket.id)


def register_actions() -> None:
    register_action(
        code="helpdesk.create_ticket_from_event",
        module="helpdesk",
        label="Creer un ticket depuis un evenement",
        function=_create_ticket_from_event,
        param_schema={
            "subject": ("Sujet du ticket (optionnel, repli 'Incident detecte automatiquement')"),
            "description": "Description du ticket (optionnel)",
            "content_type_label": (
                "Type de contenu rattache, format 'app_label.modelname' (optionnel)"
            ),
            "object_id": (
                "Identifiant de l'enregistrement rattache (optionnel, utilise avec "
                "content_type_label)"
            ),
        },
    )
