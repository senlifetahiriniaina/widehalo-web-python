"""L17 — ce que porte un document quand le tenant ne collecte pas de TVA.

**Le defaut ferme.** Depuis L5, un tenant a l'impot synthetique emet des
documents justes au CALCUL : `amount_tax` vaut zero partout, aucun compte de
TVA n'est jamais credite. Mais l'AFFICHAGE ne suivait nulle part. La facture
legale — `is_legal_document=True`, donc archivee et immuable — imprimait sans
condition :

    Total HT / Subtotal excl. tax   |  100 000 Ar
    TVA / VAT                       |        0 Ar
    Total TTC / Total incl. tax     |  100 000 Ar

« TVA : 0 » affirme qu'une taxe existe et vaut zero ; « TVA non applicable »
dit que le document n'entre pas dans le champ de la taxe. Et « HT »/« TTC »
opposent deux montants qui sont le meme.

**Ce que ces tests exercent, et qui manquait a L5.** Les gabarits que j'avais
corriges la veille conditionnaient sur `amount_tax` — un MONTANT — au lieu du
REGIME. Ils masquaient donc la meme ligne pour un non-assujetti (normal) et
pour un assujetti dont personne n'a configure d'`AccTax` (un gap de
configuration). Chaque test ci-dessous a sa moitie de falsification : le MEME
document, pour un tenant assujetti, doit porter les trois lignes."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccTax
from apps.accounting.services.legal_mentions import mandatory_vat_mention
from apps.accounting.services.public import is_vat_liable
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.services.invoicing import invoice_order
from apps.sales.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_delivered,
    start_preparation,
)

pytestmark = pytest.mark.django_db


def _tenant(code: str, regime: str) -> Tenant:
    return Tenant.objects.create(code=code, name=f"Tenant {code}", fiscal_regime=regime)


def _setup_accounting(tenant: Tenant) -> None:
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="44571")


def _invoiced_order_pdf_html(tenant: Tenant, email: str) -> str:
    """Le HTML rendu par `invoice_pdf`, sans passer par WeasyPrint.

    Le PDF binaire ne se relit pas ligne a ligne ; c'est le gabarit qu'on
    veut interroger, et `render_to_string` en est la sortie exacte."""
    from unittest.mock import patch

    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    partner = PartnerFactory(tenant=tenant)
    order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
    add_order_line(
        order,
        description="Prestation",
        qty=Decimal("1"),
        unit_price=Decimal("100000"),
        is_custom=True,
    )
    confirm_order(order, user)
    start_preparation(order, user)
    mark_delivered(order, user)
    order.refresh_from_db()
    move_id = invoice_order(order, user)
    assert move_id is not None

    from apps.accounting.services.reports import invoice_pdf

    captured: dict[str, str] = {}
    real_render = __import__(
        "django.template.loader", fromlist=["render_to_string"]
    ).render_to_string

    def _capture(template_name, context=None, *args, **kwargs):
        html = real_render(template_name, context, *args, **kwargs)
        captured["html"] = html
        return html

    with patch("django.template.loader.render_to_string", _capture):
        invoice_pdf(AccMove.objects.get(id=move_id))
    return captured["html"]


# --- La facture legale --------------------------------------------------------


def test_a_synthetic_tenant_invoice_shows_one_amount_and_no_vat_line() -> None:
    tenant = _tenant("L17-SYN", Tenant.FISCAL_REGIME_SYNTHETIC)
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        html = _invoiced_order_pdf_html(tenant, "l17-syn@example.com")

    assert "TVA" not in html.replace("TVA non applicable", "")
    assert "Total HT" not in html
    assert "Total TTC" not in html
    assert "Total / Total" in html
    assert "TVA non applicable" in html
    assert "impôt synthétique" in html


def test_a_liable_tenant_invoice_still_shows_the_three_lines() -> None:
    """La falsification. Sans elle, « on masque la TVA pour un
    non-assujetti » et « on l'a cassee pour tout le monde » seraient
    indiscernables."""
    tenant = _tenant("L17-REEL", Tenant.FISCAL_REGIME_REAL_WITH_VAT)
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant,
            code="TVA20",
            name="TVA 20%",
            type=AccTax.TYPE_SALE,
            rate=Decimal("20.000"),
        )
        _setup_accounting(tenant)
        html = _invoiced_order_pdf_html(tenant, "l17-reel@example.com")

    assert "Total HT" in html
    assert "TVA / VAT" in html
    assert "Total TTC" in html
    assert "TVA non applicable" not in html


# --- La mention ---------------------------------------------------------------


def test_the_mention_names_the_synthetic_regime_when_that_is_the_reason() -> None:
    """Deux regimes n'appellent pas la meme phrase : « impot synthetique »
    est une information que le lecteur de la facture peut verifier, « non
    assujettie » ne dit pas pourquoi."""
    synthetic = _tenant("L17-M-SYN", Tenant.FISCAL_REGIME_SYNTHETIC)
    real_no_vat = _tenant("L17-M-SANS", Tenant.FISCAL_REGIME_REAL_NO_VAT)
    liable = _tenant("L17-M-REEL", Tenant.FISCAL_REGIME_REAL_WITH_VAT)

    assert "synthétique" in mandatory_vat_mention(synthetic)
    assert "non assujettie" in mandatory_vat_mention(real_no_vat)
    assert mandatory_vat_mention(liable) == ""


def test_the_vat_option_removes_the_mention() -> None:
    """`vat_opted_in` fait basculer un `reel_sans_tva` du cote assujetti :
    la mention doit disparaitre avec, sans quoi une facture porterait a la
    fois une TVA et l'affirmation qu'elle ne s'applique pas."""
    tenant = _tenant("L17-M-OPT", Tenant.FISCAL_REGIME_REAL_NO_VAT)
    assert mandatory_vat_mention(tenant) != ""
    assert not is_vat_liable(tenant)

    tenant.vat_opted_in = True
    tenant.save(update_fields=["vat_opted_in"])
    assert mandatory_vat_mention(tenant) == ""
    assert is_vat_liable(tenant)


# --- Le calendrier fiscal -----------------------------------------------------


def test_a_synthetic_tenant_gets_no_vat_and_no_ircm_deadline() -> None:
    """Le calendrier promettait une declaration que le produit REFUSE.

    `seed_default_tax_calendar` posait les onze echeances a tout tenant sans
    lire `fiscal_regime` : un tenant synthetique recevait une echeance
    « TVA — declaration mensuelle » alors qu'il n'en collecte aucune, et une
    echeance IRCM que `generate_ircm_declaration` lui refuse par
    `ValidationError`. Une echeance fiscale inventee envoie un comptable a
    un rendez-vous qui n'existe pas."""
    from apps.accounting.models import AccTaxCalendar
    from apps.accounting.services.tax_calendar import seed_default_tax_calendar

    synthetic = _tenant("L17-CAL-SYN", Tenant.FISCAL_REGIME_SYNTHETIC)
    with use_tenant(synthetic.id):
        seed_default_tax_calendar(synthetic, year=2026)
        types = set(
            AccTaxCalendar.objects.filter(tenant=synthetic).values_list(
                "declaration_type", flat=True
            )
        )
    assert AccTaxCalendar.DECLARATION_TVA not in types
    assert AccTaxCalendar.DECLARATION_IRCM not in types
    # Les echeances qui le concernent bel et bien restent posees.
    assert AccTaxCalendar.DECLARATION_IRSA in types


def test_a_liable_tenant_still_gets_its_vat_deadline() -> None:
    """La falsification du test precedent."""
    from apps.accounting.models import AccTaxCalendar
    from apps.accounting.services.tax_calendar import seed_default_tax_calendar

    liable = _tenant("L17-CAL-REEL", Tenant.FISCAL_REGIME_REAL_WITH_VAT)
    with use_tenant(liable.id):
        seed_default_tax_calendar(liable, year=2026)
        types = set(
            AccTaxCalendar.objects.filter(tenant=liable).values_list("declaration_type", flat=True)
        )
    assert AccTaxCalendar.DECLARATION_TVA in types
    assert AccTaxCalendar.DECLARATION_IRCM in types


# --- Les seuils reglementaires ------------------------------------------------


def test_the_liability_thresholds_are_seeded_and_resolvable() -> None:
    """`tva.seuil_assujettissement` et `tva.taux_export` etaient declares par
    le cahier des charges et n'existaient dans AUCUN fichier du depot. Sans
    eux, l'ecran de configuration fiscale ne peut rapprocher aucun chiffre
    d'affaires d'aucun seuil."""
    from apps.accounting.services.vat_reference import resolve_vat_liability_thresholds

    tenant = _tenant("L17-SEUIL", Tenant.FISCAL_REGIME_SYNTHETIC)
    thresholds = resolve_vat_liability_thresholds(tenant, at_date=dt.date(2026, 6, 1))
    assert thresholds is not None
    assert thresholds["seuil_mga"] == Decimal("400000000")
    assert thresholds["plancher_option_mga"] == Decimal("200000000")


# --- Le bac a sable -----------------------------------------------------------


def test_a_sandbox_of_a_synthetic_tenant_is_synthetic() -> None:
    """`clone_tenant_to_sandbox` ne recopiait ni le regime, ni l'option, ni
    les mentions : le bac a sable d'une entreprise a l'impot synthetique
    etait un tenant assujetti a la TVA (valeur par defaut du champ). On y
    essayait donc une configuration sur un regime qui n'est pas celui de la
    societe — soit exactement ce qu'un bac a sable doit eviter."""
    from apps.core.services.sandbox import clone_tenant_to_sandbox

    source = _tenant("L17-SBX", Tenant.FISCAL_REGIME_SYNTHETIC)
    source.legal_mentions = "Escompte pour paiement anticipe : neant."
    source.save(update_fields=["legal_mentions"])

    sandbox = clone_tenant_to_sandbox(source)

    assert sandbox.fiscal_regime == Tenant.FISCAL_REGIME_SYNTHETIC
    assert sandbox.legal_mentions == source.legal_mentions
    assert not is_vat_liable(sandbox)


# --- La simulation ------------------------------------------------------------


def test_a_synthetic_tenant_can_build_a_simulation_baseline() -> None:
    """`baseline.build_baseline` LEVAIT une `ValidationError` faute de
    `tva.taux_normal`, en contradiction frontale avec
    `vat_reference.resolve_reference_vat_rate`, qui pose qu'« un tenant peut
    legitimement n'avoir aucun referentiel de TVA (regime synthetique) ».
    Deux modules affirmaient l'inverse l'un de l'autre ; celui qui levait
    avait tort, et un tenant synthetique ne pouvait construire aucun socle."""
    from apps.core.models.regulatory import RegulatoryParameter
    from apps.simulation.services.baseline import build_baseline

    tenant = _tenant("L17-SIM", Tenant.FISCAL_REGIME_SYNTHETIC)
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="l17-sim@example.com", password="Str0ngPassw0rd!23")
        # Aucun taux de TVA resolvable pour ce tenant : on retire meme le
        # parametre global, pour que le test ne reussisse pas par accident.
        RegulatoryParameter.objects.filter(code="tva.taux_normal").delete()
        baseline = build_baseline(tenant=tenant, user=user)

    assert baseline.data["tva_taux_ref"] == "0"
    assert baseline.regulatory_param_version == {}


# --- L'ecran de configuration fiscale ------------------------------------------


def _logged_in_client(tenant: Tenant, email: str):
    from django.test import Client

    with use_tenant(tenant.id):
        User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(User.objects.get(email=email))
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_the_fiscal_screen_can_switch_a_tenant_to_the_synthetic_regime() -> None:
    """Avant L17, `fiscal_regime` n'etait ecrit par AUCUNE surface du
    produit : tout tenant naissait « reel, avec TVA » — y compris une
    entreprise a l'impot synthetique — et seul le formulaire d'administration
    Django, reserve au superutilisateur, permettait de corriger."""
    tenant = _tenant("L17-ECRAN", Tenant.FISCAL_REGIME_REAL_WITH_VAT)
    client = _logged_in_client(tenant, "l17-ecran@example.com")

    response = client.post(
        "/accounting/config/fiscal/",
        {
            "fiscal_regime": Tenant.FISCAL_REGIME_SYNTHETIC,
            "legal_mentions": "Escompte : neant.",
        },
    )
    assert response.status_code == 200

    tenant.refresh_from_db()
    assert tenant.fiscal_regime == Tenant.FISCAL_REGIME_SYNTHETIC
    assert tenant.legal_mentions == "Escompte : neant."
    assert not is_vat_liable(tenant)


def test_the_fiscal_screen_refuses_an_unknown_regime_rather_than_writing_it() -> None:
    """Une chaine arbitraire postee ne doit pas atterrir dans un champ dont
    depend l'assujettissement a la TVA de toute la societe."""
    tenant = _tenant("L17-ECRAN-KO", Tenant.FISCAL_REGIME_REAL_WITH_VAT)
    client = _logged_in_client(tenant, "l17-ecran-ko@example.com")

    response = client.post("/accounting/config/fiscal/", {"fiscal_regime": "n_importe_quoi"})
    assert response.status_code == 200

    tenant.refresh_from_db()
    assert tenant.fiscal_regime == Tenant.FISCAL_REGIME_REAL_WITH_VAT


def test_the_fiscal_screen_signals_a_regime_that_no_longer_matches_the_revenue() -> None:
    """Il SIGNALE, il ne decide jamais.

    Un basculement automatique reecrirait la qualification fiscale d'une
    societe sur la foi d'un agregat interne, alors que le regime resulte
    d'une declaration a l'administration. Le chiffre est mis sous les yeux
    du comptable ; c'est lui qui tranche."""
    tenant = _tenant("L17-ECRAN-SEUIL", Tenant.FISCAL_REGIME_SYNTHETIC)
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        _post_revenue(tenant, Decimal("500000000"))
    client = _logged_in_client(tenant, "l17-ecran-seuil@example.com")

    body = client.get("/accounting/config/fiscal/").content.decode()
    assert "seuil" in body.lower()
    tenant.refresh_from_db()
    # Le regime n'a PAS bouge.
    assert tenant.fiscal_regime == Tenant.FISCAL_REGIME_SYNTHETIC


def _post_revenue(tenant: Tenant, amount: Decimal) -> None:
    """Une ecriture de vente PUBLIEE, pour que le chiffre d'affaires lu dans
    les livres soit non nul."""
    from apps.accounting.models import AccPeriod
    from apps.accounting.services.invoices import create_invoice
    from apps.accounting.services.moves import post_move

    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_SALE).first()
    period = AccPeriod.objects.filter(tenant=tenant).first()
    receivable = AccAccount.objects.filter(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE).first()
    income = AccAccount.objects.filter(tenant=tenant, type=AccAccount.TYPE_INCOME).first()
    assert journal and period and receivable and income
    move = create_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=dt.date.today(),
        partner_id=None,
        receivable_account=receivable,
        income_lines=[{"account": income, "amount": amount, "label": "Ventes"}],
    )
    post_move(move)
