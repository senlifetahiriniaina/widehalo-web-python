"""Garde-fou bloquant — l'angle mort de la Row-Level Security, rendu visible.

**Le défaut que cette garde fige n'est pas une table oubliée : c'est le
mécanisme de sélection lui-même.** `apply_rls` applique la RLS à tout
modèle héritant de `BaseModel` (`apply_rls.py`, `issubclass(model,
BaseModel)`), et son commentaire promet qu'ainsi « aucune table future de
module métier ne peut être oubliée ». C'est vrai des modèles qui héritent
de `BaseModel`. Ça ne l'est pas des autres — et **dix modèles portent un
discriminant de tenant sans en hériter**. Aucun d'eux n'apparaît nulle
part comme exception : ils sont hors périmètre, en silence.

Cette garde ne met pas ces dix tables sous RLS — ce serait un chantier à
part, au rayon de souffle large : plusieurs d'entre elles sont
délibérément interrogées hors contexte tenant, et deux au moins ne
PEUVENT pas y passer (celle qui établit l'appartenance d'un utilisateur à
un tenant, et celle qui porte la loi, commune à tous). Elle fait autre
chose, et c'est ce qui manquait : elle transforme un angle mort invisible
en **décision explicite**. Un onzième modèle échappant à la RLS fera
échouer la construction, et il faudra écrire pourquoi.

Chaque entrée porte donc son motif. Un motif qui ne convainc pas est une
table à corriger.
"""

from __future__ import annotations

from apps.core.models.base import BaseModel
from django.apps import apps as django_apps

#: Les modèles qui portent un discriminant de tenant SANS hériter de
#: `BaseModel`, donc hors du périmètre de `apply_rls`. Chacun avec la
#: raison pour laquelle il en est là — et le fait qu'une raison soit
#: écrite ne veut pas dire qu'elle est bonne : trois de ces entrées sont
#: des dettes assumées, nommées comme telles.
HORS_RLS_MOTIVES: dict[str, str] = {
    "core.UserTenantMembership": (
        "C'est la table qui ÉTABLIT à quel tenant un utilisateur appartient. La "
        "mettre sous RLS serait circulaire : il faudrait un tenant actif pour lire "
        "la ligne qui dit lequel activer. Même impasse que `PrjGuestAccess`, déjà "
        "traitée par une dérogation explicite dans `apply_rls`."
    ),
    "core.RegulatoryParameter": (
        "`tenant=None` signifie « donnée de LOI, commune à tous ». Une policy "
        "d'isolation rendrait le taux de TVA national invisible à chaque société. "
        "La surcharge par tenant, elle, est filtrée explicitement par "
        "`services/regulatory.py::_resolve_parameter`."
    ),
    "core.IdempotencyKey": (
        "DETTE ASSUMÉE (S4). Le `tenant_id` est un UUID nu parce qu'un appel peut "
        "légitimement n'avoir aucun tenant résolu. Ce n'est pas une fuite — la "
        "seule lecture du dépôt filtre sur le triplet complet et le "
        "`unique_together` porte sur ce même triplet — mais c'est un filet absent."
    ),
    "core.EventLog": (
        "DETTE ASSUMÉE. Le bus d'événements dispatche depuis un worker Django-Q "
        "sans contexte tenant : `dispatch_event(event_id)` relit la ligne pour en "
        "extraire le `tenant_id`. La mettre sous RLS demanderait de résoudre le "
        "tenant avant de lire la ligne qui le porte."
    ),
    "core.AuditLog": (
        "DETTE ASSUMÉE. Le journal d'audit est écrit par des signaux, y compris "
        "sur des opérations inter-tenants (création de société, bac à sable). "
        "C'est aussi la table qu'un audit externe doit pouvoir lire dans son "
        "ensemble — ce que la Phase 4 érige en exigence d'opposabilité."
    ),
    "core.Sequence": (
        "Interrogée par `services/sequences.py` sous `select_for_update()` avec un "
        "filtre tenant explicite, y compris depuis des commandes hors requête "
        "HTTP. L'isolation est portée par le `unique_together` (tenant, code, "
        "exercice), vérifiée par le test de concurrence SAL-6."
    ),
    "core.Notification": (
        "DETTE ASSUMÉE. Modèle générique de notification, antérieur à la "
        "discipline `BaseModel` du dépôt. `tenant_id` est un UUID nu."
    ),
    "core.WhatsAppMessage": (
        "DETTE ASSUMÉE. Même origine que `Notification`, dont elle dépend. "
        "`core` ne connaît volontairement aucun concept de `apps.whatsapp` : ni FK "
        "vers `WaConversation`, ni FK tenant — d'où l'UUID nu."
    ),
    "core.SearchDocument": (
        "Index de recherche plein texte, alimenté par signaux. Le filtrage par "
        "tenant est appliqué par le service de recherche à chaque requête."
    ),
    # `core.ApprovalRule` figurait ici, seule entrée de la liste dont le
    # motif disait « DETTE RÉELLE, ET SANS BONNE RAISON ». Elle est REMBOURSÉE :
    # `ApprovalRule` et `ApprovalRequest` héritent de `BaseModel` depuis la
    # migration `0039`, donc passent par `TenantManager` et par la policy
    # PostgreSQL comme tout le reste.
    #
    # Deux choses méritent d'être écrites plutôt que perdues.
    #
    # 1. Le motif chiffrait « les trois lecteurs — crm, payroll, patronage ».
    #    La mesure au moment de la correction en donne DIX-SEPT pour
    #    `ApprovalRule` et TREIZE pour `ApprovalRequest`. L'estimation était
    #    fausse d'un facteur six, et elle minimisait le risque : plus il y a
    #    de lecteurs, plus la probabilité qu'un seul oublie son filtre est
    #    grande. C'est exactement ce qui s'était produit dans
    #    `pending_for_user`.
    # 2. La dette a d'abord été fermée côté SERVICE (un filtre explicite),
    #    puis côté MODÈLE (cet héritage). L'ordre compte : le filtre a arrêté
    #    la fuite le jour même ; l'héritage empêche la prochaine.
}


def _models_with_a_tenant_discriminator_outside_rls() -> set[str]:
    trouves = set()
    for model in django_apps.get_models():
        if model._meta.abstract or issubclass(model, BaseModel):
            continue
        champs = {f.name for f in model._meta.get_fields()}
        if "tenant_id" in champs or "tenant" in champs:
            trouves.add(f"{model._meta.app_label}.{model.__name__}")
    return trouves


def test_no_new_model_escapes_row_level_security_unnoticed() -> None:
    """Un onzième modèle hors RLS fait échouer la construction.

    C'est le seul moment où quelqu'un se posera la question. `apply_rls`
    s'exécute sur `post_migrate` et ne dit jamais ce qu'il n'a pas couvert :
    son silence ressemble exactement à une couverture complète."""
    trouves = _models_with_a_tenant_discriminator_outside_rls()
    declares = set(HORS_RLS_MOTIVES)

    nouveaux = trouves - declares
    assert not nouveaux, (
        f"Modèle(s) portant un discriminant de tenant hors du périmètre de la "
        f"Row-Level Security, sans motif écrit : {sorted(nouveaux)}.\n"
        "Deux issues, et une seule est un raccourci : faire hériter le modèle de "
        "`BaseModel` (il passe alors sous RLS automatiquement), ou l'inscrire dans "
        "`HORS_RLS_MOTIVES` avec la raison. Un motif qui ne convainc pas est une "
        "table à corriger, pas une ligne à ajouter."
    )


def test_the_exception_list_does_not_outlive_its_entries() -> None:
    """Un modèle passé sous `BaseModel` doit sortir de la liste. Une liste
    d'exceptions qui garde des entrées obsolètes cesse d'être lue."""
    trouves = _models_with_a_tenant_discriminator_outside_rls()
    obsoletes = set(HORS_RLS_MOTIVES) - trouves
    assert not obsoletes, (
        f"Entrées obsolètes dans `HORS_RLS_MOTIVES` : {sorted(obsoletes)} — ces "
        "modèles sont désormais sous RLS et n'ont plus besoin d'exception."
    )


def test_every_exception_carries_a_real_motive() -> None:
    """Un motif d'une ligne vague vaut une absence de motif. Le seuil est
    grossier et c'est voulu : il n'attrape pas une mauvaise raison, il
    attrape l'absence de raison — le cas où quelqu'un ajoute une entrée
    pour faire passer le test précédent."""
    trop_court = {nom: m for nom, m in HORS_RLS_MOTIVES.items() if len(m) < 80}
    assert not trop_court, f"Motifs trop courts pour dire quoi que ce soit : {sorted(trop_court)}"


def test_the_detector_actually_detects() -> None:
    """Auto-test. Sans lui, `_models_with_a_tenant_discriminator_outside_rls`
    pourrait renvoyer l'ensemble vide pour une raison quelconque — un
    `issubclass` inversé, un nom de champ changé — et la garde resterait
    verte pour toujours."""
    trouves = _models_with_a_tenant_discriminator_outside_rls()
    assert "core.IdempotencyKey" in trouves, (
        "Le détecteur ne voit plus `IdempotencyKey`, dont on sait qu'elle est hors "
        "RLS : soit elle y est passée (et il faut retirer son entrée), soit le "
        "détecteur est cassé et la garde ne protège plus rien."
    )
    # Et il ne se déclenche pas sur un modèle qui EST sous RLS.
    assert "flows.FlwExchange" not in trouves
