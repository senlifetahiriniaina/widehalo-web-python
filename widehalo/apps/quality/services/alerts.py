"""Bloc D, D3 (QUA-9) : alerte de controle du/en retard — commande
planifiee comparant `QltControlPlan.frequency_days` au dernier controle
REELLEMENT constate par lot, notifie les roles qualite via
`core.services.notifications.notify_role` (meme mecanisme que
`purchase.services.price_watch`/`core.services.quality` legacy — jamais
un mecanisme d'alerte duplique).

Perimetre assume et documente : seuls les lots ayant deja recu AU MOINS
UNE mesure sous un plan peuvent etre detectes en retard.
`QltControlPlan.content_type`/`object_id` (rattachement generique) n'est
jamais renseigne dans la pratique actuelle, et `apps.quality` ne peut pas
importer `apps.stocks.models` (regle de couplage n1, cf. module.py) —
aucun mecanisme n'existe donc pour enumerer "les lots gouvernes par ce
plan" independamment de toute mesure deja prise. Un lot JAMAIS controle
ne peut donc pas etre detecte comme en retard par ce mecanisme —
lecture litterale retenue de l'enonce ("le DERNIER controle realise PAR
LOT" presuppose qu'un controle a deja eu lieu). Etendre la detection aux
lots jamais controles necessiterait un mecanisme d'enregistrement des
lots gouvernes par un plan, hors perimetre annonce de ce sprint
(`apps/quality/services/public.py` + commande de management seuls)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.notifications import notify_role_once
from apps.quality.models import QltControlPlan, QltMeasurement
from apps.quality.services.control_plans import get_last_measurement_date_for_plan

# Memes roles exacts que apps.core.services.quality.FAILURE_NOTIFICATION_ROLES
# (echec d'inspection qualite legacy) — meme rationale : incident qualite ->
# responsable production + direction.
NOTIFICATION_ROLES = ("resp_production", "direction")


def check_overdue_controls(
    tenant: Tenant, *, now: dt.datetime | None = None
) -> list[dict[str, Any]]:
    """Pour chaque `QltControlPlan` actif dont `frequency_days > 0`,
    compare le dernier controle reel (tous points critiques du plan
    confondus) de chaque lot deja mesure a la frequence attendue. Au-dela,
    notifie `NOTIFICATION_ROLES` (une notification par role, **dedoublonnee
    entre executions depuis L0-1** sur le couple plan/lot : un controle en
    retard le reste jusqu'a ce qu'il soit fait). Retourne un resume par lot en retard
    (liste de dict, jamais les objets ORM — meme discipline que
    `run_price_watch_checks`/`run_reordering`)."""
    now = now or timezone.now()
    results: list[dict[str, Any]] = []
    plans = QltControlPlan.objects.filter(tenant=tenant, is_active=True, frequency_days__gt=0)
    for plan in plans:
        lot_pairs = (
            QltMeasurement.objects.filter(critical_point__control_plan=plan)
            .exclude(lot_name="")
            .values_list("lot_variant_id", "lot_name")
            .distinct()
        )
        for lot_variant_id, lot_name in lot_pairs:
            last_measured_at = get_last_measurement_date_for_plan(
                plan, lot_variant_id=lot_variant_id, lot_name=lot_name
            )
            if last_measured_at is None:
                continue
            due_at = last_measured_at + dt.timedelta(days=plan.frequency_days)
            if due_at >= now:
                continue
            days_overdue = (now - due_at).days
            payload = {
                "control_plan_id": str(plan.id),
                "control_plan_name": plan.name,
                "lot_variant_id": str(lot_variant_id) if lot_variant_id else "",
                "lot_name": lot_name,
                "last_measured_at": last_measured_at.isoformat(),
                "days_overdue": days_overdue,
            }
            for role_code in NOTIFICATION_ROLES:
                # L0-1 : dedoublonnee sur (plan de controle, lot). Un controle
                # en retard le reste jusqu'a ce qu'il soit fait : renotifier a
                # chaque execution transformerait l'ordonnanceur en source de
                # bruit, et une alerte que l'on apprend a ignorer ne protege
                # plus de rien.
                notify_role_once(
                    str(tenant.id),
                    role_code,
                    "quality.control_overdue",
                    payload,
                    dedup_keys=("control_plan_id", "lot_variant_id", "lot_name"),
                )
            results.append(
                {
                    "control_plan_id": plan.id,
                    "control_plan_name": plan.name,
                    "lot_variant_id": lot_variant_id,
                    "lot_name": lot_name,
                    "last_measured_at": last_measured_at,
                    "days_overdue": days_overdue,
                }
            )
    return results
