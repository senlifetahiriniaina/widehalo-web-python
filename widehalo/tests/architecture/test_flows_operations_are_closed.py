"""Garde-fou bloquant — les huit opérations canoniques restent FERMÉES.

Le cahier ne laisse pas de marge : « Huit opérations canoniques et quatre
modes de déclenchement couvrent l'intégralité des liaisons identifiées en
section 3 » (décision structurante n°2), et « un connecteur se décrit alors
par le sous-ensemble d'opérations qu'il implémente, et rien de plus »
(§4.1). Un sous-ensemble suppose un ensemble ; sans jeu fermé,
`FlwConnector.supported_operations` n'est pas un sous-ensemble, c'est une
liste de chaînes.

**Ce que ce garde-fou a coûté à écrire, et qu'il faut dire.** Le jeu était
libre jusqu'au sprint S6, et cinq tests des sprints S3 à S5 s'en servaient
comme d'une étiquette — « CHEZ-A », « CASSEE », « RELEVE », « OP0 ». C'est
la preuve la plus directe qu'un champ n'est pas contraint : ses propres
tests l'emploient pour autre chose que ce qu'il désigne.

**La neuvième opération est ce qu'il faut craindre, pas la huitième.** Le
premier connecteur réel rencontrera un appel qui « n'entre dans aucune des
huit », et la tentation sera d'en ajouter une neuvième plutôt que de
composer. Le cahier a anticipé exactement cela : « le jour où cette règle
est violée, le catalogue de connecteurs devient ingérable par une personne
seule ». Le relever est une décision du commanditaire, comme les budgets de
modèles, d'écrans et d'adaptateurs.
"""

from __future__ import annotations

import pytest
from apps.flows.models import FlwConnector, FlwExchange, FlwSchedule, FlwTrigger
from apps.flows.operations import (
    INBOUND_OPERATIONS,
    OPERATION_CHOICES,
    OPERATION_CODES,
    validate_operation,
    validate_supported_operations,
)
from django.core.exceptions import ValidationError

#: Les huit du tableau §4.1, RECOPIÉES ici depuis le cahier et non
#: importées. C'est délibéré : un test qui lirait l'énumération qu'il
#: vérifie serait vert quel que soit son contenu. La duplication est le
#: mécanisme, pas un oubli — même patron que les six transformations de
#: l'axe A2.
OPERATIONS_DU_CAHIER = {"OP1", "OP2", "OP3", "OP4", "OP5", "OP6", "OP7", "OP8"}

#: « Les cinq premières opérations écrivent vers l'extérieur, les trois
#: dernières lisent ou reçoivent » (§4.1). Sur ces trois, OP8 reste
#: SORTANTE — c'est nous qui interrogeons le référentiel ; le tableau la
#: note « Sortant, lecture ». Les deux réellement entrantes sont donc OP6
#: et OP7, et c'est cette lecture-là qui est figée ici : la phrase du
#: cahier est ambiguë, le tableau ne l'est pas.
ENTRANTES_DU_CAHIER = {"OP6", "OP7"}


def test_the_operation_set_is_exactly_the_one_the_cahier_closes() -> None:
    assert OPERATION_CODES == OPERATIONS_DU_CAHIER, (
        "Le jeu d'opérations a bougé. Le cahier le ferme à huit ; le relever "
        "est une décision du commanditaire, pas un ajustement de sprint. "
        f"Manquantes : {OPERATIONS_DU_CAHIER - OPERATION_CODES} ; "
        f"en trop : {OPERATION_CODES - OPERATIONS_DU_CAHIER}."
    )


def test_the_inbound_operations_are_op6_and_op7_only() -> None:
    """Le sens fait partie de la définition. Une opération rangée du mauvais
    côté est DRAINÉE, c'est-à-dire appelée : une notification qu'on est
    censé recevoir partirait vers le tiers qui nous l'envoie."""
    assert INBOUND_OPERATIONS == ENTRANTES_DU_CAHIER


def test_every_operation_is_offered_to_the_user() -> None:
    """Une opération absente des choix n'existe que pour le code : ni
    formulaire, ni admin, ni schéma d'API ne peuvent la proposer."""
    assert {code for code, _label in OPERATION_CHOICES} == OPERATION_CODES


def test_the_three_operation_columns_all_carry_the_closed_set() -> None:
    """Trois modèles portent une colonne `operation` — planification,
    déclencheur, échange. Fermer deux d'entre elles et pas la troisième
    laisserait le trou exactement là où il compte : la planification écrit
    l'échange, et une valeur libre en amont ressort en aval."""
    for modele in (FlwSchedule, FlwTrigger, FlwExchange):
        champ = modele._meta.get_field("operation")
        assert champ.choices, f"{modele.__name__}.operation n'est pas contraint."
        assert {code for code, _label in champ.choices} == OPERATION_CODES, modele.__name__


def test_the_connector_field_carries_its_validator() -> None:
    """Le validateur seul ne suffit pas — Django ne le fait tourner que
    dans `full_clean()` — mais l'ôter du champ priverait formulaires et
    schémas de la seule contrainte qu'ils sachent lire. Il est donc exigé
    aux DEUX endroits, ici et dans `save()` (test suivant)."""
    champ = FlwConnector._meta.get_field("supported_operations")
    assert validate_supported_operations in champ.validators


@pytest.mark.django_db
def test_the_connector_refuses_a_ninth_operation_on_save() -> None:
    """L'autre moitié : `save()` valide explicitement, parce que Django ne
    le fait pas. Sans ce rappel, tout ce qui écrit par l'ORM — un import
    d'archive, une migration de données, un script d'exploitation —
    passerait à côté du jeu fermé."""
    from apps.core.models.tenant import Tenant
    from apps.core.tests.utils import use_tenant
    from apps.flows.tests.factories import FlwConnectorFactory

    tenant = Tenant.objects.create(code="GARDE-OPS", name="Garde SARL")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        FlwConnectorFactory(tenant=tenant, supported_operations=["OP9"])


def test_the_detector_catches_a_ninth_operation() -> None:
    """Auto-test : une garde qui ne détecte rien reste verte pour
    toujours. Ce dépôt le vérifie partout ailleurs — il n'y a pas de raison
    d'en dispenser celle-ci."""
    with pytest.raises(ValidationError):
        validate_operation("OP9")
    with pytest.raises(ValidationError):
        validate_supported_operations(["OP1", "OP9"])
    with pytest.raises(ValidationError):
        validate_supported_operations("OP1")
    # Et le témoin, sans lequel un validateur qui refuserait TOUT laisserait
    # les trois assertions ci-dessus vertes.
    assert validate_operation("OP1") == "OP1"
    validate_supported_operations(sorted(OPERATIONS_DU_CAHIER))


@pytest.mark.parametrize("code", sorted(OPERATIONS_DU_CAHIER))
def test_each_operation_keeps_the_cahier_s_own_reference(code: str) -> None:
    """« OP1 »…« OP8 », et pas un nom parlant. Le cahier les désigne ainsi
    dans son tableau, dans ses critères et dans ses blocs ; les renommer
    ferait perdre la seule correspondance vérifiable entre le code et le
    document qui l'exige."""
    assert code.startswith("OP")
    assert code[2:].isdigit()
