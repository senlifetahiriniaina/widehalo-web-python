"""STR-1 (L8) — l'objectif mesurable etait impossible sur une instance
neuve, et personne ne le voyait.

Le critere : « Objectif sans indicateur du dictionnaire refuse ;
avancement calcule depuis l'indicateur, jamais saisi. »

La garde existait et fonctionnait : `activate_objective` refuse tout
objectif dont aucun resultat cle ne porte un `metric_code` publie, et
`add_key_result` refuse un code inconnu. Les tests de `strategy` la
verifiaient — en enregistrant eux-memes l'indicateur dont ils avaient
besoin.

**Ce que ces tests ajoutent, et pourquoi il le fallait.** Sur une instance
reelle, RIEN ne peuplait `AnMetricDefinition` : aucune migration, aucune
commande, aucun chemin de creation de tenant. Aucun `metric_code` n'existait
donc jamais, donc aucun resultat cle mesurable ne pouvait etre cree, donc
AUCUN objectif ne pouvait etre active. La garde etait satisfaite en test et
insatisfiable en production — un critere vert sur une fonctionnalite
inaccessible.

Ces tests partent donc d'un tenant cree par le chemin reel
(`create_tenant`), sans enregistrer aucun indicateur eux-memes.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import (
    activate_objective,
    add_key_result,
    create_objective,
)

pytestmark = pytest.mark.django_db


def _fresh_tenant() -> Tenant:
    code = f"STG-L8-{uuid.uuid4().hex[:6]}"
    call_command("create_tenant", code=code, name="Tenant neuf")
    return Tenant.objects.get(code=code)


def _objective(tenant: Tenant) -> StgObjective:
    return create_objective(
        tenant,
        title="Croissance",
        level=StgObjective.LEVEL_COMPANY,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 12, 31),
    )


def test_a_freshly_created_tenant_can_activate_a_measurable_objective() -> None:
    """Le coeur : sur un tenant cree par le chemin reel, sans qu'aucun
    test n'enregistre d'indicateur, un objectif mesurable est desormais
    constructible de bout en bout. Avant L8, `add_key_result` refusait
    « Code indicateur inconnu ou non publie » pour tout code — le
    dictionnaire etant vide."""
    tenant = _fresh_tenant()
    with use_tenant(tenant.id):
        objective = _objective(tenant)

        key_result = add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            metric_code="sales.ca_ht",
        )

        assert key_result.metric_code == "sales.ca_ht"
        assert activate_objective(objective) is objective


def test_an_objective_without_a_dictionary_metric_is_still_refused() -> None:
    """La garde STR-1 n'est pas relachee par L8 : un resultat cle sans
    indicateur gouverne ne rend toujours pas l'objectif activable."""
    tenant = _fresh_tenant()
    with use_tenant(tenant.id):
        objective = _objective(tenant)
        add_key_result(objective, metric_name="Ressenti terrain", target_value=Decimal("100"))

        with pytest.raises(ValidationError):
            activate_objective(objective)


def test_an_unknown_metric_code_is_still_refused() -> None:
    """Le dictionnaire peuple ne doit pas ouvrir la porte a n'importe quel
    code : seul un code PUBLIE du catalogue est accepte."""
    tenant = _fresh_tenant()
    with use_tenant(tenant.id):
        objective = _objective(tenant)

        with pytest.raises(ValidationError, match="Code indicateur inconnu"):
            add_key_result(
                objective,
                metric_name="Inventé",
                target_value=Decimal("1"),
                metric_code="sales.code_invente",
            )
