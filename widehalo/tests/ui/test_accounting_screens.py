from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_module_access, use_tenant
from apps.core.utils.formatting import format_mga
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def accounting_screens_setup():
    tenant = Tenant.objects.create(code="UI-ACC", name="UI Accounting Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-acc@example.com", password="Str0ngPassw0rd!23")
        # C-1 : les ecrans de ce module verifient desormais un droit.
        # `grant_module_access` plutot que `grant_role` — les seuls roles
        # qui detiennent accounting en ecriture sont soumis au MFA obligatoire,
        # et `force_login` renverrait alors vers /mfa/.
        grant_module_access(user, "accounting")
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        receivable = AccAccount.objects.create(
            tenant=tenant, code="411000", name="Clients", account_class="4", type="receivable"
        )
        income = AccAccount.objects.create(
            tenant=tenant, code="701000", name="Ventes", account_class="7", type="income"
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, journal, receivable, income


def test_invoice_create_screen_then_appears_in_list(accounting_screens_setup) -> None:
    client, tenant, journal, receivable, income = accounting_screens_setup

    create_response = client.post(
        "/accounting/new/",
        {
            "journal_id": str(journal.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "income_account_id": str(income.id),
            "label": "Vente tissus",
            "amount": "500000",
        },
    )
    assert create_response.status_code == 302

    # **`X or status_code == 200` est TOUJOURS vrai** : la seconde branche
    # tient des que la page se rend, donc l'assertion ne portait sur rien.
    # Et le montant s'affiche au format de la locale depuis E-3.
    # **La reference est l'OBJET CREE, pas un montant ecrit d'avance.** Ma
    # premiere version cherchait « 500 000 Ar » — le montant poste — et
    # ignorait que la facture porte la TVA : son total debiteur vaut
    # davantage. Un test qui suppose le calcul qu'il observe finit par
    # mesurer sa propre supposition.
    with use_tenant(tenant.id):
        facture = AccMove.objects.filter(move_type=AccMove.TYPE_CUSTOMER_INVOICE).latest(
            "created_at"
        )
    list_response = client.get("/accounting/?presentation=liste")
    assert list_response.status_code == 200
    contenu = list_response.content.decode()
    assert facture.reference in contenu, "La facture creee n'apparait pas dans la liste."
    assert format_mga(facture.total_debit) in contenu, (
        "Le montant de la facture n'est pas rendu au format de la locale."
    )


def test_invoice_list_screen_renders(accounting_screens_setup) -> None:
    client, _tenant, _journal, _receivable, _income = accounting_screens_setup
    response = client.get("/accounting/?presentation=liste")
    assert response.status_code == 200
    contenu = response.content.decode()
    # L'ecran se rend : il doit au moins porter ses en-tetes de colonnes,
    # accentues depuis E-1. Un gabarit vide rendrait 200 lui aussi.
    assert "Référence" in contenu and "Montant (MGA)" in contenu


def _posted_invoice_for_payment(client, tenant, journal, receivable, income):
    from apps.accounting.models import AccJournal, AccMove
    from apps.accounting.services.invoices import (
        ensure_default_approval_thresholds,
        validate_invoice,
    )
    from apps.core.models.user import User
    from apps.core.tests.utils import use_tenant
    from django.contrib.auth.models import Group, Permission

    with use_tenant(tenant.id):
        bank_journal = AccJournal.objects.create(
            tenant=tenant, code="BQ", name="Banque", type=AccJournal.TYPE_BANK, sequence_prefix="BQ"
        )
        bank_account = AccAccount.objects.create(
            tenant=tenant, code="512000", name="Banque", account_class="5", type="bank"
        )
        gain = AccAccount.objects.create(
            tenant=tenant, code="766000", name="Gains de change", account_class="7", type="income"
        )
        loss = AccAccount.objects.create(
            tenant=tenant, code="666000", name="Pertes de change", account_class="6", type="expense"
        )
        ensure_default_approval_thresholds(tenant)
        comptable = User.objects.create_user(
            email="ui-acc-comptable@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="comptable")
        permission = Permission.objects.get(
            codename="validate_accmove", content_type__app_label="accounting"
        )
        group.permissions.add(permission)
        comptable.groups.add(group)

    create_response = client.post(
        "/accounting/new/",
        {
            "journal_id": str(journal.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "income_account_id": str(income.id),
            "label": "Vente tissus",
            "amount": "1000",
        },
    )
    assert create_response.status_code == 302
    invoice_id = create_response.url.rstrip("/").split("/")[-1]

    with use_tenant(tenant.id):
        invoice = AccMove.objects.get(id=invoice_id)
        validate_invoice(invoice, comptable)

    return invoice_id, bank_journal, bank_account, gain, loss


def test_invoice_payment_registration_shows_allocation(accounting_screens_setup) -> None:
    client, tenant, journal, receivable, income = accounting_screens_setup
    invoice_id, bank_journal, bank_account, gain, loss = _posted_invoice_for_payment(
        client, tenant, journal, receivable, income
    )

    payment_response = client.post(
        f"/accounting/{invoice_id}/",
        {
            "action": "register_payment",
            "payment_journal_id": str(bank_journal.id),
            "cash_account_id": str(bank_account.id),
            "gain_account_id": str(gain.id),
            "loss_account_id": str(loss.id),
            "payment_amount": "1000",
            "payment_date": "2026-01-20",
            "method": "virement",
        },
    )
    assert payment_response.status_code == 302

    detail = client.get(f"/accounting/{invoice_id}/")
    assert detail.status_code == 200
    assert b"virement" in detail.content.lower() or b"Virement" in detail.content
    assert b"1000" in detail.content


def test_imports_screens_render(accounting_screens_setup) -> None:
    """Chantier import comptable/caisse — les 3 ecrans HTMX sont
    atteignables en session (jamais l'API JWT en interne).

    H-2b : ce test n'asserait qu'un code de statut, et figurait a ce titre
    dans la dette declaree de `test_screen_tests_assert_content`. Trois
    ecrans vides auraient rendu 200 tout autant. On verifie desormais ce
    que chacun ANNONCE — son titre et son etat vide."""
    client, _tenant, _journal, _receivable, _income = accounting_screens_setup

    index = client.get("/accounting/config/imports/")
    assert index.status_code == 200
    assert "Aucun import." in index.content.decode()

    chart = client.get("/accounting/config/imports/chart-of-accounts/")
    assert chart.status_code == 200
    assert "Import du plan comptable" in chart.content.decode()

    cash_journal = client.get("/accounting/config/imports/cash-journal/")
    assert cash_journal.status_code == 200
    assert "Import du journal de caisse" in cash_journal.content.decode()


def test_imports_screens_never_reference_the_internal_docs_file(accounting_screens_setup) -> None:
    """L'utilisateur final n'a pas connaissance des fichiers source — plus
    aucun ecran ne doit renvoyer vers docs/IMPORT_FORMATS.md."""
    client, _tenant, _journal, _receivable, _income = accounting_screens_setup

    chart = client.get("/accounting/config/imports/chart-of-accounts/")
    cash_journal = client.get("/accounting/config/imports/cash-journal/")
    assert b"IMPORT_FORMATS" not in chart.content
    assert b"IMPORT_FORMATS" not in cash_journal.content
    assert "Télécharger le modèle Excel" in chart.content.decode()


def test_download_chart_of_accounts_template_round_trips(accounting_screens_setup) -> None:
    """Le modele telechargeable doit etre accepte tel quel par l'import
    reel — sinon la promesse du bouton n'est pas tenue."""
    from apps.accounting.services.chart_of_accounts_import import import_chart_of_accounts_xlsx
    from apps.core.tests.utils import use_tenant

    client, tenant, _journal, _receivable, _income = accounting_screens_setup

    response = client.get("/accounting/config/imports/chart-of-accounts/template.xlsx")
    assert response.status_code == 200
    assert response["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "modele_import_plan_comptable.xlsx" in response["Content-Disposition"]

    with use_tenant(tenant.id):
        summary = import_chart_of_accounts_xlsx(tenant, response.content)
    assert summary.is_valid
    assert summary.created_count == 1


def test_download_cash_journal_template_round_trips(accounting_screens_setup) -> None:
    """Le modele telechargeable doit avoir ses en-tetes reconnus par
    l'import reel — verifie via un journal de caisse (TYPE_CASH) portant
    le meme nom que la caisse d'exemple du modele, pour que la ligne
    s'importe sans aucune anomalie bloquante. La date d'exemple du modele
    (date du jour) est recalee sur la periode ouverte du tenant de test
    (janvier 2026) — sans rapport avec la reconnaissance des en-tetes, qui
    est le seul point verifie ici. Le modele n'a pas de colonne
    Fournisseur/Client/Partenaire (RG-QUALIF, chantier posterieur a ce
    modele) : la ligne resout donc un partenaire "placeholder" et reste
    `needs_qualification` plutot que `ok` — jamais bloquant, une AccMove
    reelle est quand meme creee (verifie ci-dessous), c'est la seule
    difference attendue avec un import "propre"."""
    import io

    from apps.accounting.models import AccJournal
    from apps.accounting.services.cash_journal_import import import_cash_journal_xlsx
    from apps.core.tests.utils import use_tenant
    from openpyxl import load_workbook

    client, tenant, _journal, _receivable, income = accounting_screens_setup

    response = client.get("/accounting/config/imports/cash-journal/template.xlsx")
    assert response.status_code == 200
    assert response["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "modele_import_journal_caisse.xlsx" in response["Content-Disposition"]

    workbook = load_workbook(io.BytesIO(response.content))
    sheet = workbook.active
    sheet["A2"] = dt.date(2026, 1, 15)
    buffer = io.BytesIO()
    workbook.save(buffer)

    with use_tenant(tenant.id):
        AccJournal.objects.create(
            tenant=tenant,
            code="CAISSE",
            name="CAISSE PRINCIPALE",
            type=AccJournal.TYPE_CASH,
            sequence_prefix="CAI",
            default_account=income,
        )
        batch = import_cash_journal_xlsx(tenant, buffer.getvalue())
        row_move = batch.batch.rows.get().move
    assert batch.total_rows == 1
    assert batch.needs_qualification_count == 1
    assert batch.unresolvable_count == 0
    assert row_move is not None


def test_bank_reconciliation_screen_renders_its_upload_and_its_confidence(
    accounting_screens_setup,
) -> None:
    """H-2b — l'ecran de BNK-3, qu'AUCUN test ne rendait.

    BNK-3 exige une confirmation HUMAINE : `suggest_matches` passe une
    ligne a `rule_suggested`, jamais a `matched`. Cet ecran est donc le
    seul endroit du produit ou le comptable arbitre une proposition de
    rapprochement — et il n'etait atteint que par le crawler generique,
    qui ne verifie qu'un statut par construction."""
    client, tenant, *_ = accounting_screens_setup

    # Le formulaire de chargement n'est rendu QUE si la societe a un compte
    # de tresorerie : `_comptes_bancaires` filtre sur `bank`/`cash`. Sans
    # lui l'ecran repond 200 en n'affichant rien — et un test de statut
    # seul l'aurait declare sain.
    from apps.accounting.models import AccBankStatementLine

    with use_tenant(tenant.id):
        compte_bancaire = AccAccount.objects.create(
            tenant=tenant,
            code="512000",
            name="Banque",
            account_class="5",
            type=AccAccount.TYPE_BANK,
        )
        # La colonne « Confiance » — le barème de BNK-3 — n'apparaît qu'avec
        # des lignes à arbitrer. Sans relevé chargé, l'écran est un
        # formulaire vide : c'est justement ce qu'un test de statut seul
        # aurait pris pour un écran sain.
        AccBankStatementLine.objects.create(
            tenant=tenant,
            bank_account=compte_bancaire,
            import_batch_id=uuid.uuid4(),
            statement_date=dt.date(2026, 1, 20),
            reference_external="VIR-2026-0001",
            label="Virement client SARL Nord",
            amount_mga=Decimal("450000"),
            direction=AccBankStatementLine.DIRECTION_IN,
            state=AccBankStatementLine.STATE_RULE_SUGGESTED,
            match_confidence=80,
        )

    reponse = client.get("/accounting/bank/")
    assert reponse.status_code == 200

    contenu = reponse.content.decode()
    for attendu in ("Charger le relevé", "Compte de trésorerie", "Confiance"):
        assert attendu in contenu, f"« {attendu} » absent de l'écran de rapprochement"
    assert "Virement client SARL Nord" in contenu, "la ligne de relevé à arbitrer n'est pas rendue"


def test_default_accounts_screen_lists_the_roles_it_maps(accounting_screens_setup) -> None:
    """H-2b — la matrice role -> compte, qu'aucun test ne rendait.

    C'est elle qui decide quel compte recoit une commission d'encaissement
    ou un passage de tresorerie : une matrice vide se voit a la premiere
    ecriture automatique, pas avant."""
    client, *_ = accounting_screens_setup

    reponse = client.get("/accounting/config/default-accounts/")
    assert reponse.status_code == 200

    contenu = reponse.content.decode()
    for attendu in ("Comptes par défaut du tenant", "Rôle", "Compte configuré"):
        assert attendu in contenu, f"« {attendu} » absent de l'écran des comptes par défaut"


def test_cash_journal_batch_detail_shows_its_rows_and_their_anomalies(
    accounting_screens_setup,
) -> None:
    """H-2b — le jumeau oublie.

    `imports/invoices_batch_detail.html` est couvert depuis G-4 ; son
    jumeau du journal de caisse ne l'etait pas. Le crawler generique ne
    pouvait pas le voir : la route prend un parametre de chemin, et il
    saute ces routes-la. Une asymetrie, pas une decision."""
    from apps.accounting.models import AccImportBatch, AccImportRow

    client, tenant, journal, _receivable, _income = accounting_screens_setup

    with use_tenant(tenant.id):
        lot = AccImportBatch.objects.create(
            tenant=tenant,
            kind=AccImportBatch.KIND_CASH_JOURNAL,
            source_filename="caisse-janvier.xlsx",
            format_version=1,
            journal=journal,
            total_rows=1,
            anomaly_rows_count=1,
        )
        AccImportRow.objects.create(
            tenant=tenant,
            batch=lot,
            row_number=1,
            raw_data={"libelle": "Achat de fournitures", "montant": "12500"},
            status=AccImportRow.STATUS_NEEDS_QUALIFICATION,
            anomaly_codes=["compte_inconnu"],
            # Le selecteur « Compte réel » n'est propose QUE sur une ligne
            # posee sur un compte d'attente : c'est le cas qui appelle une
            # qualification, et donc celui que cet ecran sert.
            uses_placeholder_account=True,
        )

    reponse = client.get(f"/accounting/config/imports/cash-journal/{lot.id}/")
    assert reponse.status_code == 200

    contenu = reponse.content.decode()
    assert "caisse-janvier.xlsx" in contenu
    assert "Achat de fournitures" in contenu, "la ligne du lot n'est pas rendue"
    assert "Compte réel" in contenu
