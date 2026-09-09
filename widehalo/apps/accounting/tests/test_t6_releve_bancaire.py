"""T6 (bloc E, BNK-1 à BNK-3) — ce que le chargement d'un relevé doit tenir.

**Écrit AVANT la correction, pour mesurer plutôt qu'affirmer.** Le plan
annonçait « aucune détection de doublon » et « aucune isolation de ligne
fautive ». La mesure dit pire, et c'est la combinaison des deux qui coûte :
`import_bank_statement` lève sur la PREMIÈRE ligne fautive, alors que les
lignes précédentes sont déjà écrites — aucun `transaction.atomic` nulle
part dans le module. Un relevé dont la ligne 50 est mal formée laisse donc
49 lignes en base, rend un 400 à l'utilisateur, et le ré-essai après
correction du fichier en ajoute 49 autres.

Les deux critères se répondent : sans BNK-2 (isolation), BNK-1 (doublon)
devient la conséquence normale du premier fichier imparfait.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccBankStatementLine
from apps.accounting.services.bank_reconciliation import import_bank_statement
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

#: Un relevé ordinaire : trois lignes propres.
RELEVE_PROPRE = (
    b"date,reference,label,amount,direction\n"
    b"2026-01-05,VIR-001,Virement client,150000,in\n"
    b"2026-01-06,CHQ-002,Cheque fournisseur,42000,out\n"
    b"2026-01-07,VIR-003,Virement client,90000,in\n"
)

#: Le même relevé, la deuxième ligne illisible. C'est le cas courant : un
#: export de banque dont une ligne porte un montant vide ou une date au
#: format local.
RELEVE_AVEC_LIGNE_FAUTIVE = (
    b"date,reference,label,amount,direction\n"
    b"2026-01-05,VIR-001,Virement client,150000,in\n"
    b"2026-01-06,CHQ-002,Cheque fournisseur,PAS UN MONTANT,out\n"
    b"2026-01-07,VIR-003,Virement client,90000,in\n"
)


@pytest.fixture
def compte_bancaire():
    tenant = Tenant.objects.create(code="ACC-T6", name="Flux bancaires")
    with use_tenant(tenant.id):
        compte = AccAccount.objects.create(
            tenant=tenant,
            code="512",
            name="Banque",
            account_class=5,
            type=AccAccount.TYPE_BANK,
        )
    return tenant, compte


def test_a_faulty_line_does_not_stop_the_batch(compte_bancaire) -> None:
    """**BNK-2** : « une ligne de relevé en anomalie n'interrompt pas le
    chargement du lot ; elle est isolée dans un rapport de chargement
    exploitable ».

    Deux lignes sur trois sont parfaitement lisibles : elles doivent
    entrer. La troisième est isolée, nommée, et l'exploitant sait laquelle
    reprendre — un refus global l'obligerait à chercher lui-même la ligne
    fautive dans un export de plusieurs centaines."""
    tenant, compte = compte_bancaire
    with use_tenant(tenant.id):
        rapport = import_bank_statement(compte, RELEVE_AVEC_LIGNE_FAUTIVE)

        assert len(rapport.lines) == 2, (
            "Les lignes lisibles doivent être chargées ; refuser le lot entier "
            "pour une ligne mal formée est ce que BNK-2 interdit."
        )
        assert len(rapport.rejected) == 1
        assert rapport.rejected[0].line_number == 3, (
            "Le rapport doit NOMMER la ligne : sans son numéro, l'exploitant "
            "cherche à l'œil dans un export de plusieurs centaines de lignes."
        )
        assert "PAS UN MONTANT" in rapport.rejected[0].reason


def test_a_faulty_line_never_leaves_a_half_loaded_batch(compte_bancaire) -> None:
    """**Le défaut mesuré, et il combine BNK-1 et BNK-2.** Avant correction,
    l'import écrivait ligne à ligne puis levait : les lignes précédant
    l'anomalie restaient en base, l'appelant recevait un 400, et le
    ré-essai après correction du fichier les dupliquait.

    Un lot est donc chargé ENTIÈREMENT ou pas du tout, la part rejetée
    étant décrite plutôt qu'écrite."""
    tenant, compte = compte_bancaire
    with use_tenant(tenant.id):
        import_bank_statement(compte, RELEVE_AVEC_LIGNE_FAUTIVE)
        lignes = list(AccBankStatementLine.objects.filter(bank_account=compte))

    assert len(lignes) == 2
    assert {ligne.reference_external for ligne in lignes} == {"VIR-001", "VIR-003"}


def test_reloading_the_same_statement_creates_no_duplicate(compte_bancaire) -> None:
    """**BNK-1** : « le rechargement d'un relevé déjà importé ne crée aucun
    doublon de ligne **et le signale explicitement** ».

    Les deux moitiés comptent. Ne pas dupliquer sans rien dire laisserait
    l'exploitant croire que son second chargement n'a pas fonctionné, et il
    recommencerait — sur un autre compte, ou en renommant le fichier."""
    tenant, compte = compte_bancaire
    with use_tenant(tenant.id):
        premier = import_bank_statement(compte, RELEVE_PROPRE)
        second = import_bank_statement(compte, RELEVE_PROPRE)

        assert len(premier.lines) == 3
        assert second.already_imported, (
            "Le rechargement doit être SIGNALÉ, pas seulement absorbé en silence."
        )
        assert len(second.lines) == 0
        assert AccBankStatementLine.objects.filter(bank_account=compte).count() == 3


def test_a_different_statement_on_the_same_account_still_loads(compte_bancaire) -> None:
    """La détection porte sur le CONTENU, jamais sur le compte ou la date.

    Un relevé hebdomadaire chargé le lundi puis un autre le mardi sont deux
    relevés différents du même compte : les confondre bloquerait le
    chargement courant, ce qui serait pire que le doublon qu'on évite."""
    tenant, compte = compte_bancaire
    autre_releve = RELEVE_PROPRE + b"2026-01-08,VIR-004,Virement client,10000,in\n"
    with use_tenant(tenant.id):
        import_bank_statement(compte, RELEVE_PROPRE)
        second = import_bank_statement(compte, autre_releve)

        assert not second.already_imported
        # **Seule la ligne NEUVE entre**, et c'est le cas courant : les
        # relevés se recouvrent. Charger les quatre dupliquerait trois
        # opérations ; refuser le fichier entier priverait l'exploitant de
        # la quatrième. La déduplication porte donc sur la LIGNE, ce que
        # BNK-1 demande mot pour mot — « aucun doublon DE LIGNE ».
        assert len(second.lines) == 1
        assert second.lines[0].reference_external == "VIR-004"
        assert len(second.duplicates) == 3
        assert AccBankStatementLine.objects.filter(bank_account=compte).count() == 4


def test_a_suggestion_carries_its_timestamp_and_confidence(compte_bancaire) -> None:
    """**BNK-3** : « le moteur produit des propositions **horodatées** avec
    un **niveau de confiance** ».

    Ce sont les deux mots du critère que le moteur ne portait pas. Sans
    horodatage, on ne sait pas si une proposition date d'avant la dernière
    écriture — donc si elle vaut encore. Sans niveau de confiance, une
    correspondance sur le seul montant se présente comme une
    correspondance sur montant ET référence ET tiers."""
    from apps.accounting.models import AccReconcileRule
    from apps.accounting.services.bank_reconciliation import suggest_matches

    tenant, compte = compte_bancaire
    with use_tenant(tenant.id):
        AccReconcileRule.objects.create(
            tenant=tenant,
            name="Montant seul",
            bank_account=compte,
            match_on_amount=True,
            amount_tolerance_mga=Decimal("0"),
            priority=10,
        )
        _ecriture_bancaire(tenant, compte, montant=Decimal("150000"), libelle="VIR-001")
        import_bank_statement(compte, RELEVE_PROPRE)

        suggerees = suggest_matches(compte)
        assert suggerees, "La règle sur le montant devait proposer une correspondance."
        ligne = suggerees[0]
        assert ligne.suggested_at is not None
        assert 0 < ligne.match_confidence <= 100
        assert ligne.matched_by_rule_id is not None, (
            "Sans la règle qui a proposé, l'exploitant ne peut ni juger la "
            "proposition ni corriger la règle qui la produit."
        )


def _ecriture_bancaire(tenant, compte, *, montant: Decimal, libelle: str):
    """Une écriture publiée sur le compte de banque, candidate au
    rapprochement."""
    from apps.accounting.models import AccFiscalYear, AccJournal, AccPeriod
    from apps.accounting.services.moves import add_line, create_draft_move, post_move

    exercice = AccFiscalYear.objects.create(
        tenant=tenant,
        code="FY2026",
        date_start=dt.date(2026, 1, 1),
        date_end=dt.date(2026, 12, 31),
    )
    periode = AccPeriod.objects.create(
        tenant=tenant,
        fiscal_year=exercice,
        code="2026-01",
        date_start=dt.date(2026, 1, 1),
        date_end=dt.date(2026, 1, 31),
    )
    journal = AccJournal.objects.create(
        tenant=tenant, code="BQ", name="Banque", type=AccJournal.TYPE_BANK, sequence_prefix="BQ"
    )
    contrepartie = AccAccount.objects.create(
        tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
    )
    piece = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=periode,
        date=dt.date(2026, 1, 5),
        narration="Encaissement",
    )
    add_line(piece, account=compte, label=libelle, debit=montant)
    add_line(piece, account=contrepartie, label=libelle, credit=montant)
    return post_move(piece)
