"""MRP-FSM1 (enrichissement WideHalo) : suivi d'approvisionnement par
composant, independant de l'etat de l'ordre de fabrication."""

from __future__ import annotations

from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.mrp.models import MrpBomLineState, MrpOrderComponent


def get_or_create_procurement_state(component: MrpOrderComponent) -> MrpBomLineState:
    state, _created = MrpBomLineState.objects.get_or_create(
        tenant=component.tenant, order_component=component
    )
    return state


def _apply(state: MrpBomLineState, method_name: str, user: User) -> MrpBomLineState:
    attempt_transition(state, method_name, user)
    state.save(update_fields=["state"])
    return state


def request_sample(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "request_sample", user)


def evaluate_sample(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "evaluate_sample", user)


def validate_supplier(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "validate_supplier", user)


def order(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "order", user)


def receive(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "receive", user)


def declare_shortage(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "declare_shortage", user)


def send_to_quality_control(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "send_to_quality_control", user)


def approve(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "approve", user)


def reject(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "reject", user)


def start_production(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "start_production", user)


def consume(state: MrpBomLineState, user: User) -> MrpBomLineState:
    return _apply(state, "consume", user)
