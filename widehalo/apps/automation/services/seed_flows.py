"""INT4 (chantier interactivite native inter-modules — « faire le max avec
AutoFlow ») : jeu de flux `AutoFlow` REELS branches sur les `event_type`
publies par INT1 (et les evenements preexistants `risk.flagged`/
`ai.anomaly_detected`/`helpdesk.ticket_escalated`), construits UNIQUEMENT
avec le contrat deja etabli par `apps.automation.services.flows`
(`create_flow`/`add_condition_step`/`add_action_step`/`set_flow_active`) —
jamais un acces direct aux modeles `AutoFlow`/`AutoStep`.

**Idempotence** : chaque flux est identifie par son `name`, UNIQUE dans ce
jeu de donnees pour un tenant donne (verifie par `AutoFlow.objects.filter(
tenant=tenant, name=...).exists()` avant toute creation, jamais un flux en
double a un second passage de la commande `seed_automation_flows`) — un
flux deja present n'est jamais recree NI reconfigure (aucune tentative de
"reparer" un flux qu'un utilisateur aurait modifie depuis le Studio).

**Activation** : chaque flux nouvellement cree est active
(`set_flow_active(flow, is_active=True)`) des sa construction complete —
jamais laisse a l'etat brouillon par defaut de `create_flow`, ces flux sont
concus pour fonctionner reellement des le seed (cf. plan INT4)."""

from __future__ import annotations

from collections.abc import Callable

from apps.automation.models import AutoFlow
from apps.automation.services.flows import (
    add_action_step,
    add_condition_step,
    create_flow,
    set_flow_active,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User


def _get_or_build(
    tenant: Tenant, name: str, builder: Callable[[], AutoFlow]
) -> tuple[AutoFlow, bool]:
    """Renvoie `(flow, created)` — `created=False` sans rien reconstruire
    si un flux `name` existe deja pour ce tenant, `created=True` (flux
    construit puis active par l'appelant) sinon."""
    existing = AutoFlow.objects.filter(tenant=tenant, name=name).first()
    if existing is not None:
        return existing, False
    return builder(), True


# `name` (identifiant d'idempotence, cf. `_get_or_build`) est le PREMIER
# parametre de chaque builder, jamais duplique separement dans une table de
# correspondance — source unique de verite, cf. `_FLOW_SPECS` en pied de
# module qui appaire chaque builder au meme literal `name`.


def _build_purchase_order_confirmed(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="purchase.order_confirmed",
        description=(
            "A la confirmation d'une commande fournisseur, notifie le magasinier "
            "pour anticiper la reception de marchandise."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "magasinier",
            "notification_type": "purchase.order_confirmed",
            "payload": {
                "order_id": "=payload['order_id']",
                "reference": "=payload['reference']",
                "amount_total_mga": "=payload['amount_total_mga']",
            },
        },
    )
    return flow


def _build_sales_order_blocked(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="sales.order_blocked",
        description=(
            "Blocage credit d'une commande client : notifie direction ET comptable "
            "avec le motif et l'encours."
        ),
        created_by=created_by,
    )
    payload_mapping = {
        "order_id": "=payload['order_id']",
        "reference": "=payload['reference']",
        "reason": "=payload['reason']",
        "outstanding_amount_mga": "=payload['outstanding_amount_mga']",
    }
    notify_comptable = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "comptable",
            "notification_type": "sales.order_blocked",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "sales.order_blocked",
            "payload": payload_mapping,
        },
        next_step=notify_comptable,
    )
    return flow


def _build_purchase_reorder_triggered(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="purchase.reorder_triggered",
        description=(
            "Un reapprovisionnement automatique a genere des demandes d'achat : "
            "notifie l'acheteur pour revue."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "acheteur",
            "notification_type": "purchase.reorder_triggered",
            "payload": {
                "requisition_ids": "=payload['requisition_ids']",
                "count": "=payload['count']",
            },
        },
    )
    return flow


def _build_accounting_invoice_validated(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="accounting.invoice_validated",
        description="A la validation d'une facture (achat/vente), notifie le comptable.",
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "comptable",
            "notification_type": "accounting.invoice_validated",
            "payload": {
                "move_id": "=payload['move_id']",
                "move_type": "=payload['move_type']",
            },
        },
    )
    return flow


def _build_accounting_invoice_cancelled(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="accounting.invoice_cancelled",
        description="Annulation d'une facture : notifie comptable ET direction avec le motif.",
        created_by=created_by,
    )
    payload_mapping = {
        "move_id": "=payload['move_id']",
        "move_type": "=payload['move_type']",
        "motif": "=payload['motif']",
    }
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "accounting.invoice_cancelled",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "comptable",
            "notification_type": "accounting.invoice_cancelled",
            "payload": payload_mapping,
        },
        next_step=notify_direction,
    )
    return flow


def _build_financing_credoc_opened(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="financing.credoc_state_changed",
        description=(
            "Le credoc reutilise UN SEUL event_type pour tout son cycle de vie "
            "(cf. apps.financing.services.credoc) : ce flux filtre par une CONDITION "
            "sur payload['state'] == 'ouvert' pour ne notifier qu'a l'ouverture reelle "
            "du credoc, jamais a chaque transition (demande/documents_recus/paye/clos)."
        ),
        created_by=created_by,
    )
    payload_mapping = {
        "credoc_id": "=payload['credoc_id']",
        "reference": "=payload['reference']",
        "state": "=payload['state']",
    }
    notify_comptable = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "comptable",
            "notification_type": "financing.credoc_state_changed",
            "payload": payload_mapping,
        },
    )
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "financing.credoc_state_changed",
            "payload": payload_mapping,
        },
        next_step=notify_comptable,
    )
    add_condition_step(
        flow,
        expression="payload['state'] == 'ouvert'",
        next_step=notify_direction,
    )
    return flow


def _build_payroll_period_validated(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="payroll.period_validated",
        description="Validation d'une periode de paie : notifie RH ET direction.",
        created_by=created_by,
    )
    payload_mapping = {
        "period_id": "=payload['period_id']",
        "code": "=payload['code']",
    }
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "payroll.period_validated",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "rh",
            "notification_type": "payroll.period_validated",
            "payload": payload_mapping,
        },
        next_step=notify_direction,
    )
    return flow


def _build_logistics_shipment_blocked(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="logistics.shipment_blocked",
        description="Blocage d'une expedition : notifie resp_production ET direction.",
        created_by=created_by,
    )
    payload_mapping = {
        "shipment_id": "=payload['shipment_id']",
        "reference": "=payload['reference']",
        "reason": "=payload['reason']",
    }
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "logistics.shipment_blocked",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "resp_production",
            "notification_type": "logistics.shipment_blocked",
            "payload": payload_mapping,
        },
        next_step=notify_direction,
    )
    return flow


def _build_purchase_dispute_notify(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="purchase.dispute_opened",
        description=(
            "Ouverture d'un litige sur une commande fournisseur : notifie acheteur ET direction."
        ),
        created_by=created_by,
    )
    payload_mapping = {
        "order_id": "=payload['order_id']",
        "reference": "=payload['reference']",
        "partner_id": "=payload['partner_id']",
        "reason": "=payload['reason']",
    }
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "purchase.dispute_opened",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "acheteur",
            "notification_type": "purchase.dispute_opened",
            "payload": payload_mapping,
        },
        next_step=notify_direction,
    )
    return flow


def _build_purchase_dispute_open_incident(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="purchase.dispute_opened",
        description=(
            "En plus de la notification (cf. flux dedie), ouvre automatiquement un "
            "incident fournisseur (purchase.open_incident) trace pour suivi, a partir "
            "du fournisseur et du motif portes par l'evenement."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="purchase.open_incident",
        param_mapping={
            "partner_id": "=payload['partner_id']",
            "description": "=payload['reason']",
            "type": "litige",
        },
    )
    return flow


def _build_reporting_job_failed(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="reporting.job_failed",
        description="Echec d'un job de generation de rapport : notifie admin ET direction.",
        created_by=created_by,
    )
    payload_mapping = {
        "job_id": "=payload['job_id']",
        "report_code": "=payload['report_code']",
        "error_message": "=payload['error_message']",
    }
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "reporting.job_failed",
            "payload": payload_mapping,
        },
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "admin",
            "notification_type": "reporting.job_failed",
            "payload": payload_mapping,
        },
        next_step=notify_direction,
    )
    return flow


def _build_risk_flagged_routing(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    """Un SEUL flux, trois branches conditionnelles chainees selon
    `payload['category']` (cf. `apps.core.models.risk.CATEGORY_CHOICES`) —
    demonstration reelle du graphe conditionnel du Studio, pas une simple
    notification a une seule etape. Construit "de bas en haut" (les
    feuilles d'abord) car `add_condition_step`/`add_action_step`
    referencent des `AutoStep` deja crees."""
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="risk.flagged",
        description=(
            "RiskItem de score eleve : route la notification selon "
            "payload['category'] — fournisseur -> acheteur, logistique -> "
            "resp_production, financier -> comptable + direction. Categories "
            "restantes (production/qualite/rh/projet/autre) : aucune action, jamais "
            "un flux bloquant."
        ),
        created_by=created_by,
    )
    payload_mapping = {
        "risk_item_id": "=payload['risk_item_id']",
        "category": "=payload['category']",
        "score": "=payload['score']",
    }

    notify_supplier = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "acheteur",
            "notification_type": "risk.flagged",
            "payload": payload_mapping,
        },
    )
    notify_logistics = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "resp_production",
            "notification_type": "risk.flagged",
            "payload": payload_mapping,
        },
    )
    notify_financial_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "risk.flagged",
            "payload": payload_mapping,
        },
    )
    notify_financial_comptable = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "comptable",
            "notification_type": "risk.flagged",
            "payload": payload_mapping,
        },
        next_step=notify_financial_direction,
    )
    financial_check = add_condition_step(
        flow,
        expression="payload['category'] == 'financier'",
        next_step=notify_financial_comptable,
        next_step_on_false=None,
    )
    logistics_check = add_condition_step(
        flow,
        expression="payload['category'] == 'logistique'",
        next_step=notify_logistics,
        next_step_on_false=financial_check,
    )
    add_condition_step(
        flow,
        expression="payload['category'] == 'fournisseur'",
        next_step=notify_supplier,
        next_step_on_false=logistics_check,
    )
    return flow


def _build_ai_anomaly_detected(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="ai.anomaly_detected",
        description=(
            "Anomalie haute detectee par apps.ai : cree un ticket helpdesk "
            "d'incident rattache a l'entite source (helpdesk.create_ticket_from_event) "
            "PUIS notifie direction."
        ),
        created_by=created_by,
    )
    notify_direction = add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "ai.anomaly_detected",
            "payload": {
                "anomaly_id": "=payload['anomaly_id']",
                "check_code": "=payload['check_code']",
                "severity": "=payload['severity']",
            },
        },
    )
    add_action_step(
        flow,
        action_code="helpdesk.create_ticket_from_event",
        param_mapping={
            "subject": "Anomalie IA detectee automatiquement",
            "description": "=payload['check_code']",
            "content_type_label": "=payload['content_type_label']",
            "object_id": "=payload['object_id']",
        },
        next_step=notify_direction,
    )
    return flow


def _build_helpdesk_ticket_escalated(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="helpdesk.ticket_escalated",
        description="Escalade (manuelle ou automatique) d'un ticket helpdesk : notifie direction.",
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="core.notify_role",
        param_mapping={
            "role_code": "direction",
            "notification_type": "helpdesk.ticket_escalated",
            "payload": {
                "ticket_id": "=payload['ticket_id']",
                "reference": "=payload['reference']",
            },
        },
    )
    return flow


def _build_crm_opportunity_stage_changed(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="crm.opportunity_stage_changed",
        description=(
            "Changement d'etape (y compris gagnee/perdue) d'une opportunite : notifie "
            "resp_commercial."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="crm.notify_role_of_opportunity",
        param_mapping={
            "role_code": "resp_commercial",
            "lead_id": "=payload['lead_id']",
            "note": "=payload['stage_name']",
            "notification_type": "crm.opportunity_stage_changed",
        },
    )
    return flow


def _build_catalog_variants_generated(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="catalog.variants_generated",
        description=(
            "Generation automatique de variantes produit : notifie resp_production "
            "pour verification."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="catalog.notify_role_of_catalog_issue",
        param_mapping={
            "role_code": "resp_production",
            "template_id": "=payload['template_id']",
            "note": "=payload['count']",
            "notification_type": "catalog.variants_generated",
        },
    )
    return flow


def _build_partners_duplicate_alert(tenant: Tenant, name: str, created_by: User | None) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="partners.duplicate_alert_created",
        description=(
            "Doublon detecte a la creation d'un partenaire (meme NIF) : notifie "
            "direction pour revue."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="partners.notify_role_of_duplicate",
        param_mapping={
            "role_code": "direction",
            "partner_id": "=payload['partner_id']",
            "duplicate_of_id": "=payload['duplicate_of_id']",
            "note": "=payload['matched_field']",
            "notification_type": "partners.duplicate_alert_created",
        },
    )
    return flow


def _build_patronage_pattern_version_changed(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="patronage.pattern_version_changed",
        description="Nouvelle version d'un patron de coupe : notifie resp_production.",
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="patronage.notify_role_of_pattern_version",
        param_mapping={
            "role_code": "resp_production",
            "pattern_id": "=payload['pattern_id']",
            "note": "=payload['version']",
            "notification_type": "patronage.pattern_version_changed",
        },
    )
    return flow


def _build_feasibility_study_completed(
    tenant: Tenant, name: str, created_by: User | None
) -> AutoFlow:
    flow = create_flow(
        tenant,
        name=name,
        trigger_event_type="feasibility.study_completed",
        description=(
            "Fin d'une etude de faisabilite : notifie direction ET resp_commercial "
            "(repli par defaut de feasibility.notify_study_completed)."
        ),
        created_by=created_by,
    )
    add_action_step(
        flow,
        action_code="feasibility.notify_study_completed",
        param_mapping={
            "study_id": "=payload['study_id']",
            "note": "=payload['name']",
            "notification_type": "feasibility.study_completed",
        },
    )
    return flow


# Source UNIQUE de verite `(name, builder)` — `name` sert a la fois de
# libelle du flux et de cle d'idempotence (cf. `_get_or_build`), jamais
# duplique dans une table de correspondance separee. Ordre disclosed : suit
# l'ordre du plan INT4 (evenements INT1 dans l'ordre de
# `PUBLISHED_EVENT_TYPES`, puis les evenements preexistants pertinents).
_FLOW_SPECS: tuple[tuple[str, Callable[[Tenant, str, User | None], AutoFlow]], ...] = (
    ("Commande fournisseur confirmee -> notifier magasinier", _build_purchase_order_confirmed),
    (
        "Commande client bloquee (credit) -> notifier direction et comptable",
        _build_sales_order_blocked,
    ),
    (
        "Reapprovisionnement automatique -> notifier acheteur",
        _build_purchase_reorder_triggered,
    ),
    ("Facture validee -> notifier comptable", _build_accounting_invoice_validated),
    (
        "Facture annulee -> notifier comptable et direction",
        _build_accounting_invoice_cancelled,
    ),
    ("Credoc ouvert -> notifier direction et comptable", _build_financing_credoc_opened),
    (
        "Periode de paie validee -> notifier RH et direction",
        _build_payroll_period_validated,
    ),
    (
        "Expedition bloquee -> notifier resp_production et direction",
        _build_logistics_shipment_blocked,
    ),
    (
        "Litige fournisseur ouvert -> notifier acheteur et direction",
        _build_purchase_dispute_notify,
    ),
    (
        "Litige fournisseur ouvert -> ouvrir un incident fournisseur",
        _build_purchase_dispute_open_incident,
    ),
    ("Job de reporting en echec -> notifier admin et direction", _build_reporting_job_failed),
    ("Risque signale (score eleve) -> routage par categorie", _build_risk_flagged_routing),
    ("Anomalie IA detectee -> ticket + notifier direction", _build_ai_anomaly_detected),
    ("Ticket helpdesk escalade -> notifier direction", _build_helpdesk_ticket_escalated),
    (
        "Opportunite CRM changee d'etape -> notifier resp_commercial",
        _build_crm_opportunity_stage_changed,
    ),
    (
        "Variantes catalogue generees -> notifier resp_production",
        _build_catalog_variants_generated,
    ),
    ("Doublon partenaire detecte -> notifier direction", _build_partners_duplicate_alert),
    (
        "Nouvelle version de patron -> notifier resp_production",
        _build_patronage_pattern_version_changed,
    ),
    (
        "Etude de faisabilite terminee -> notifier direction et resp_commercial",
        _build_feasibility_study_completed,
    ),
)


def seed_default_flows(
    tenant: Tenant, *, created_by: User | None = None
) -> list[tuple[AutoFlow, bool]]:
    """Construit (si absents) le jeu complet de flux INT4 pour `tenant`,
    active chaque flux NOUVELLEMENT cree, et renvoie `[(flow, created), ...]`
    dans l'ordre de `_FLOW_SPECS` — jamais un flux recree ni retouche s'il
    existe deja (identifie par `name`, cf. `_get_or_build`)."""
    results: list[tuple[AutoFlow, bool]] = []
    for name, builder in _FLOW_SPECS:

        def _build(
            builder: Callable[[Tenant, str, User | None], AutoFlow] = builder,
            name: str = name,
        ) -> AutoFlow:
            return builder(tenant, name, created_by)

        flow, created = _get_or_build(tenant, name, _build)
        if created:
            set_flow_active(flow, is_active=True)
        results.append((flow, created))
    return results
