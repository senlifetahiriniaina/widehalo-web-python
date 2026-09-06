"""Le coût imputé de l'échange — attribut oublié par le sprint S1.

Le cahier n'en fait pas un détail : c'est sa **décision structurante n°6**
(« tout échange porte un coût imputé et un plafond opposable ») et §13.2 le
liste explicitement parmi les attributs de l'échange, au même titre que
l'empreinte ou la clé de corrélation.

Le modèle livré en S1 n'en avait aucun. Sans ce champ, le plafond
transverse annoncé pour la Phase 4 n'aurait rien à compter, et l'arbitrage
H26 — bascule de l'unité de coût de la messagerie, dû au sprint S3 —
n'aurait aucun endroit où atterrir.

Le défaut n'a été trouvé qu'en relisant le cahier **attribut par attribut**
contre le modèle livré. Un modèle qui « a l'air complet » ne l'est pas pour
autant, et c'est exactement le motif que ce projet corrige depuis le début :
du code correct et bien documenté, à côté duquel une exigence entière
manque sans que rien ne le signale.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.services.exchange import prepare_exchange
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="S2-COST", name="Flux coût SARL")
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant)
    return tenant, link


def test_an_exchange_carries_an_imputed_cost_field(setup) -> None:
    """`None` à la préparation, et c'est le point : « coût non encore
    imputé » et « coût nul » sont deux choses différentes.

    Une soumission fiscale gratuite vaut zéro ; un échange dont le tarif
    n'est pas encore connu vaut `None`. Les confondre ferait mentir tout
    total — un plafond calculé sur des zéros implicites autoriserait des
    envois que le vrai coût aurait bloqués."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = prepare_exchange(tenant, link, operation="OP1")
        assert exchange.cost_ariary is None

        exchange.cost_ariary = Decimal("0")
        exchange.save(update_fields=["cost_ariary"])
        exchange.refresh_from_db()

    assert exchange.cost_ariary == Decimal("0")
    assert exchange.cost_ariary is not None


def test_no_tariff_is_hardcoded_in_the_flows_module() -> None:
    """« Aucun tarif n'est écrit dans le code : les grilles rejoignent la
    table de paramètres versionnés livrée en Phase 1 » (cahier, même
    décision structurante).

    Le champ porte un montant **imputé**, résultat d'une grille, jamais la
    grille elle-même. C'est précisément le défaut que L3 et L17 ont dû
    corriger ailleurs dans ce dépôt : des paramètres réglementaires codés
    en dur plutôt que semés, donc inéditables sans livraison."""
    flows_dir = Path(__file__).resolve().parent.parent
    montant_decimal = re.compile(r"Decimal\(\s*['\"]\d")

    suspects: list[str] = []
    for path in sorted(flows_dir.rglob("*.py")):
        parts = path.parts
        if "tests" in parts or "migrations" in parts:
            continue
        for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if montant_decimal.search(line):
                suspects.append(f"{path.name}:{num}: {line.strip()}")

    assert not suspects, (
        "Tarif potentiellement codé en dur dans `apps/flows` — les grilles "
        "appartiennent à la table de paramètres versionnés :\n" + "\n".join(suspects)
    )


def test_the_tariff_detector_actually_detects(tmp_path: Path) -> None:
    """Auto-test du détecteur. Sans lui, le test précédent serait vert
    quelle que soit sa capacité à voir un tarif — et `apps/flows` n'en
    contient aucun aujourd'hui, donc son zéro ne prouve rien par
    lui-même."""
    montant_decimal = re.compile(r"Decimal\(\s*['\"]\d")

    assert montant_decimal.search('    cout = Decimal("120.00")')
    assert montant_decimal.search("    cout = Decimal('50')")
    # ... et il ne se déclenche pas sur un usage légitime de Decimal.
    assert not montant_decimal.search("    total = Decimal(0)")
    assert not montant_decimal.search("    montant = Decimal(str(valeur))")
