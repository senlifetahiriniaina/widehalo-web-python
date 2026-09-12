from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import DateTimeField, ExpressionWrapper, F, Q, QuerySet
from django.utils import timezone

from apps.core.context import get_current_tenant_id
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalDelegation, ApprovalRequest, ApprovalRule

#: Le type de notification emis quand une demande est creee. Chaine libre
#: (le champ n'a pas de jeu ferme) mais nommee en un seul endroit.
NOTIFICATION_DEMANDE = "approval.requested"


def _qualification_decision_hooks() -> dict[tuple[str, str], Any]:
    """Effets de bord metier APRES la decision generique.

    Registre {(app_label, model): callable}, resolu PARESSEUSEMENT pour ne
    jamais faire dependre le chargement de `core` de celui des apps metier
    — `core` ne peut importer QUE `apps.<module>.services.public` (regle de
    couplage n°1).

    **Deplace ici depuis `api_workflow.py`**, ou il ne servait que l'API :
    l'ecran de validation doit produire EXACTEMENT le meme effet, et deux
    chemins de decision qui divergeraient finiraient par ne pas rendre le
    meme resultat."""
    from apps.accounting.services.public import (
        decide_budget_approval,
        decide_cash_journal_qualification,
        decide_invoice_import_qualification,
    )
    from apps.purchase.services.public import decide_reordering_proposal
    from apps.stocks.services.public import decide_stock_import_qualification

    return {
        ("accounting", "accbudget"): decide_budget_approval,
        ("accounting", "accimportrow"): decide_cash_journal_qualification,
        ("accounting", "accinvoiceimportrow"): decide_invoice_import_qualification,
        ("stocks", "stkimportrow"): decide_stock_import_qualification,
        ("purchase", "purreorderingproposal"): decide_reordering_proposal,
    }


def decide_and_propagate(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> ApprovalRequest:
    """Decide, puis repercute sur la piece metier quand elle l'exige.

    Seul point d'entree commun a l'API et a l'ecran de validation."""
    decide(approval_request, decided_by, approved=approved, comment=comment)
    hook = _qualification_decision_hooks().get(
        (approval_request.content_type.app_label, approval_request.content_type.model)
    )
    if hook is not None:
        hook(approval_request.id, decided_by, approved=approved, comment=comment)
    return approval_request


def request_approval(
    obj: Any, rule: ApprovalRule, requested_by: User, comment: str = ""
) -> ApprovalRequest:
    """La societe de la demande est celle de LA REGLE, jamais celle du
    contexte actif.

    Ce n'est pas une nuance : la regle est l'objet qui decide qui valide, et
    une demande rattachee a une autre societe que sa regle serait invisible
    de sa propre lecture (qui verifie les deux). Prendre la societe de la
    regle rend cette divergence impossible a la CREATION plutot qu'a la
    lecture."""
    demande = ApprovalRequest.objects.create(
        tenant_id=rule.tenant_id,
        rule=rule,
        content_type=ContentType.objects.get_for_model(obj.__class__),
        object_id=str(obj.pk),
        requested_by=requested_by,
        comment=comment,
    )
    # **Prevenir l'approbateur, sinon personne ne sait.** Une demande creee
    # en silence attend un geste que son destinataire n'a aucune raison
    # d'aller chercher : c'est exactement ce qui laissait les factures
    # bloquees. On reutilise la notification par role du socle plutot que
    # d'inventer un second canal.
    if rule.approver_role:
        from apps.core.services.notifications import notify_role

        notify_role(
            str(rule.tenant_id),
            rule.approver_role,
            NOTIFICATION_DEMANDE,
            {
                "rule_name": rule.name,
                "requested_by": requested_by.email,
                "object_id": str(obj.pk),
            },
        )
    return demande


def pending_for_object(obj: Any) -> QuerySet[ApprovalRequest]:
    """Les demandes en attente SUR CETTE PIECE.

    Sert le rappel affiche sur la fiche : sans lui, celui qui consulte une
    facture qui refuse de se valider doit deviner pourquoi. La question se
    pose sur la piece ; la reponse doit y etre."""
    return ApprovalRequest.objects.filter(
        content_type=ContentType.objects.get_for_model(obj.__class__),
        object_id=str(obj.pk),
        status=ApprovalRequest.STATUS_PENDING,
    ).select_related("rule")


def _delegate_ids_for(user: User) -> list[Any]:
    now = timezone.now()
    return list(
        ApprovalDelegation.objects.filter(
            delegate=user, valid_from__lte=now, valid_to__gte=now
        ).values_list("delegator_id", flat=True)
    )


def pending_for_user(user: User) -> QuerySet[ApprovalRequest]:
    """Demandes en attente adressees a l'utilisateur DANS CETTE SOCIETE :
    celles ou son role est l'approbateur principal, celles deleguees vers
    lui (delegation explicite), et celles escaladees vers son role de
    secours faute de decision dans le delai `rule.escalate_after` (cascade
    de validateurs de secours — l'absence reelle d'un validateur, elle,
    sera detectee plus tard par le futur module Presence/RH ; ici
    l'escalade est purement temporelle).

    **`tenant_id` est OBLIGATOIRE, et c'est la correction.** Cette fonction
    ne filtrait sur aucune societe : un utilisateur portant le role
    « comptable » voyait les demandes de TOUTE societe dont une regle porte
    ce role. Les groupes Django sont globaux dans ce depot — le seul role
    ne peut donc pas decider ce qu'on voit.

    Rien ne rattrapait l'oubli AU MOMENT DE LA CORRECTION :
    `ApprovalRequest` n'avait aucune colonne de tenant (sa societe se
    deduisait par `rule.tenant`), il n'y avait donc rien d'evident a
    filtrer, et ni ce modele ni `ApprovalRule` ne passaient par
    `TenantManager` ou la securite au niveau des lignes.

    **Ce filet existe depuis.** Les deux modeles heritent desormais de
    `BaseModel` : `objects` filtre sur la societe active, et PostgreSQL
    refuse les lignes des autres. Le filtre ci-dessous devient donc
    REDONDANT — et il reste, deliberement. Il porte quelque chose que le
    manager ne porte pas : la verification que la demande ET SA REGLE
    appartiennent bien a la meme societe. Une divergence rendrait la
    demande invisible, jamais visible a tort.

    **La societe vient du CONTEXTE ACTIF, jamais d'un parametre ni de
    l'objet.** Les trois options ont ete pesees :

    - la deduire de `approval_request.rule.tenant` rendrait le controle
      TAUTOLOGIQUE — on comparerait la societe de l'objet a elle-meme ;
    - un parametre explicite obligerait la dizaine d'enveloppes de
      `services/public.py` a le fournir, soit dix occasions de passer la
      mauvaise valeur, a commencer par la premiere sous la main : celle de
      l'objet ;
    - le contexte actif est la societe de L'APPELANT, pose par
      `TenantMiddleware` depuis la requete authentifiee. Il n'y a rien a
      fournir, donc rien a se tromper.

    C'est aussi le mecanisme que tout le reste du depot emploie deja —
    `TenantManager` et la securite au niveau des lignes lisent le meme
    contextvar. Etre coherent avec lui n'est pas un compromis ici, c'est
    l'inverse d'une exception.

    Hors contexte de societe, on ne renvoie RIEN plutot que tout : meme
    discipline deny-by-default que `TenantManager`."""
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        return ApprovalRequest.objects.none()

    delegator_ids = _delegate_ids_for(user)
    approver_roles = set(user.groups.values_list("name", flat=True))

    qs = ApprovalRequest.objects.filter(rule__tenant_id=tenant_id).annotate(
        escalates_at=ExpressionWrapper(
            F("created_at") + F("rule__escalate_after"), output_field=DateTimeField()
        )
    )
    return qs.filter(
        Q(status=ApprovalRequest.STATUS_PENDING)
        & (
            Q(rule__approver_role__in=approver_roles)
            | Q(requested_by_id__in=delegator_ids)
            | (
                Q(rule__fallback_approver_role__in=approver_roles)
                & Q(rule__escalate_after__isnull=False)
                & Q(escalates_at__lte=timezone.now())
            )
        )
    )


def is_eligible_approver(approval_request: ApprovalRequest, user: User) -> bool:
    """Reprend exactement les 3 conditions de `pending_for_user` (role
    approbateur principal / delegation explicite / escalade de secours
    apres `rule.escalate_after`), mais evaluees pour UNE demande deja
    identifiee plutot que pour filtrer un queryset — utilisee par
    `decide()` pour empecher un utilisateur authentifie quelconque de
    decider d'une demande qui ne lui est pas adressee (RG-WF-DECIDE,
    correctif d'un controle d'acces manquant : `decide_approval` n'avait
    aucune verification d'eligibilite avant ce correctif)."""
    rule = approval_request.rule
    # LA SOCIETE D'ABORD, avant tout examen de role. Voir la demande d'une
    # autre societe est une indiscretion ; en DECIDER est un acte qui
    # engage cette societe — approuver sa facture, sa periode de paie, sa
    # commande. Ce controle manquait entierement : seuls les roles etaient
    # compares, et les groupes Django sont globaux.
    tenant_id = get_current_tenant_id()
    if not tenant_id or str(rule.tenant_id) != str(tenant_id):
        return False

    approver_roles = set(user.groups.values_list("name", flat=True))

    if rule.approver_role and rule.approver_role in approver_roles:
        return True
    if approval_request.requested_by_id in _delegate_ids_for(user):
        return True
    return (
        bool(rule.fallback_approver_role)
        and rule.fallback_approver_role in approver_roles
        and rule.escalate_after is not None
        and timezone.now() >= approval_request.created_at + rule.escalate_after
    )


def decide(
    request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> ApprovalRequest:
    if not is_eligible_approver(request, decided_by):
        raise PermissionDenied(
            "Cet utilisateur n'est pas un approbateur eligible pour cette demande "
            "(societe, role approbateur, delegation ou escalade de secours requis)."
        )
    request.status = (
        ApprovalRequest.STATUS_APPROVED if approved else ApprovalRequest.STATUS_REJECTED
    )
    request.decided_by = decided_by
    request.decided_at = timezone.now()
    request.comment = comment
    request.save(update_fields=["status", "decided_by", "decided_at", "comment"])
    return request


def delegate_approval(
    delegator: User, delegate: User, valid_from: Any, valid_to: Any, scope: str = ""
) -> ApprovalDelegation:
    return ApprovalDelegation.objects.create(
        delegator=delegator,
        delegate=delegate,
        valid_from=valid_from,
        valid_to=valid_to,
        scope=scope,
    )
