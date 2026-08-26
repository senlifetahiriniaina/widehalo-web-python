"""Coeur comptable (Lot 2, phase 1) : plan comptable PCG 2005, exercices et
periodes, journaux. Les ecritures (AccMove/AccMoveLine) sont ajoutees a
l'etape A2, la TVA/regimes fiscaux a l'etape A3."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class AccFiscalYear(BaseModel):
    STATE_OPEN = "open"
    STATE_CLOSING = "closing"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouvert"),
        (STATE_CLOSING, "En cloture"),
        (STATE_CLOSED, "Cloture"),
    ]

    code = models.CharField(max_length=16)
    date_start = models.DateField()
    date_end = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)

    class Meta:
        db_table = "acc_fiscal_year"

    def __str__(self) -> str:
        return self.code


class AccPeriod(BaseModel):
    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouverte"),
        (STATE_CLOSED, "Close"),
    ]

    fiscal_year = models.ForeignKey(AccFiscalYear, on_delete=models.CASCADE, related_name="periods")
    code = models.CharField(max_length=16)
    date_start = models.DateField()
    date_end = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)

    class Meta:
        db_table = "acc_period"

    def __str__(self) -> str:
        return self.code


class AccAccount(BaseModel):
    TYPE_ASSET = "asset"
    TYPE_LIABILITY = "liability"
    TYPE_EQUITY = "equity"
    TYPE_INCOME = "income"
    TYPE_EXPENSE = "expense"
    TYPE_RECEIVABLE = "receivable"
    TYPE_PAYABLE = "payable"
    TYPE_BANK = "bank"
    TYPE_CASH = "cash"
    TYPE_TAX = "tax"
    TYPE_STOCK = "stock"
    TYPE_CHOICES = [
        (TYPE_ASSET, "Actif"),
        (TYPE_LIABILITY, "Passif"),
        (TYPE_EQUITY, "Capitaux propres"),
        (TYPE_INCOME, "Produit"),
        (TYPE_EXPENSE, "Charge"),
        (TYPE_RECEIVABLE, "Creance"),
        (TYPE_PAYABLE, "Dette"),
        (TYPE_BANK, "Banque"),
        (TYPE_CASH, "Caisse"),
        (TYPE_TAX, "Taxe"),
        (TYPE_STOCK, "Stock"),
    ]

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    account_class = models.PositiveSmallIntegerField(help_text="Classe PCG, 1 a 7")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    reconcilable = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="MGA")
    is_active = models.BooleanField(default=True)
    # RG-ACC-9 : distribution analytique obligatoire (somme = 100%) sur les
    # lignes portees par ce compte — configurable par compte, cf. etape A6.
    analytic_required = models.BooleanField(default=False)

    class Meta:
        db_table = "acc_account"
        indexes = [models.Index(fields=["code"])]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class AccJournal(BaseModel):
    TYPE_SALE = "sale"
    TYPE_PURCHASE = "purchase"
    TYPE_BANK = "bank"
    TYPE_CASH = "cash"
    TYPE_MISC = "misc"
    TYPE_PAYROLL = "payroll"
    TYPE_STOCK = "stock"
    TYPE_CHOICES = [
        (TYPE_SALE, "Ventes"),
        (TYPE_PURCHASE, "Achats"),
        (TYPE_BANK, "Banque"),
        (TYPE_CASH, "Caisse"),
        (TYPE_MISC, "Operations diverses"),
        (TYPE_PAYROLL, "Paie"),
        (TYPE_STOCK, "Stock"),
    ]

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    default_account = models.ForeignKey(
        AccAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sequence_prefix = models.CharField(max_length=16)
    currency = models.CharField(max_length=3, default="MGA")

    class Meta:
        db_table = "acc_journal"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
