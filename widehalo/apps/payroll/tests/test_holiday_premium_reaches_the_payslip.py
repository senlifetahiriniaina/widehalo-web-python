"""Un jour férié travaillé vaut 100 % de prime — et cette prime n'arrivait
jamais au bulletin.

**Le défaut, mesuré.** `payroll.overtime_multipliers` porte
`"ferie": "2.00"` depuis le lot E1, et `expr.py` l'applique correctement.
Mais `presence.services.public` n'exposait qu'un TOTAL d'heures validées,
« toutes catégories de majoration confondues », et `payslip.py` imputait
donc l'intégralité à `h_sup_30` — la majoration la plus faible du barème.

Une heure de jour férié était payée **1,30 au lieu de 2,00**, soit 35 % de
moins que le dû. La catégorie était pourtant saisie par l'utilisateur,
validée par un responsable et stockée en base : elle se perdait à la
dernière marche, sans que rien ne proteste.

**Ce fichier compare des MONTANTS**, pas la présence d'une clef. Un test qui
vérifierait que `resolved_overtime_hours` contient `"ferie"` passerait sans
rien dire du bulletin.

Le chiffrage tient sur un salaire choisi pour donner un taux horaire rond :
1 040 000 Ar / (26 jours × 8 h) = **5 000 Ar l'heure**. Dix heures de férié
valent donc 10 × 5 000 × 2,00 = **100 000 Ar**, contre 65 000 Ar sous
l'ancien repli.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.calendar import declare_holiday
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.models import PrsOvertime
from apps.presence.services.overtime import record_overtime, validate_overtime
from apps.presence.tests.factories import PrsEmployeeFactory

pytestmark = pytest.mark.django_db

#: 1 040 000 / (26 × 8) = 5 000 Ar l'heure, exactement.
SALAIRE_BASE = Decimal("1040000")
TAUX_HORAIRE = Decimal("5000")


def _ligne(payslip: PayPayslip, code: str) -> Decimal:
    """`lines` est une relation, pas une liste — même accès que
    `test_overtime_multipliers.py`.

    À LIRE DANS LE CONTEXTE DE LA SOCIÉTÉ : `PayPayslipLine` hérite de
    `BaseModel`, donc `objects` ne rend rien hors contexte. Une première
    rédaction de ce fichier lisait la ligne après la sortie du bloc
    `use_tenant` et obtenait un `DoesNotExist` — un faux échec qui ne disait
    rien du montant."""
    return payslip.lines.get(code=code).amount


def _societe_avec_paie(code: str) -> Tenant:
    tenant = Tenant.objects.create(code=code, name=f"Paie {code}")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
    return tenant


def _heures_declarees(tenant, *, date: dt.date, categorie: str, heures: str, valideur):
    employe = PrsEmployeeFactory(tenant=tenant)
    heures_sup = record_overtime(employe, date=date, hours=Decimal(heures), rate_category=categorie)
    validate_overtime(heures_sup, valideur)
    return employe


def test_a_worked_holiday_hour_is_paid_double_not_one_point_three(django_user_model) -> None:
    """**Le test qui chiffre le défaut.** Dix heures déclarées un jour férié,
    aucune ventilation passée à la main : le bulletin doit les payer 2,00."""
    tenant = _societe_avec_paie("PAY-FERIE-1")
    valideur = django_user_model.objects.create_user(
        email="valideur.ferie@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        # Un 26 juin — fête de l'Indépendance — dans la période de paie.
        jour_ferie = dt.date(2026, 3, 16)
        declare_holiday(tenant, date=jour_ferie, name="Journée électorale")
        employe = _heures_declarees(
            tenant,
            date=jour_ferie,
            categorie=PrsOvertime.RATE_HOLIDAY,
            heures="10",
            valideur=valideur,
        )
        contract = make_active_contract(tenant, employee_id=employe.id, wage_base=SALAIRE_BASE)
        period = make_period(tenant)
        # AUCUN `overtime_hours` : c'est le chemin de repli, celui qui était
        # cassé. La ventilation doit être lue dans `presence`.
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employe.id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        montant = _ligne(payslip, "HEURES_SUP")

    assert montant == Decimal("10") * TAUX_HORAIRE * Decimal("2.00"), (
        f"Heures de jour férié payées {montant} Ar au lieu de 100 000 Ar. "
        "Si le montant vaut 65 000, la ventilation par catégorie ne remonte pas "
        "de `presence` et tout est imputé à `h_sup_30` (1,30) — le défaut d'origine."
    )


def test_the_five_categories_each_keep_their_own_multiplier(django_user_model) -> None:
    """L'écrasement ne frappait pas que le férié : `dimanche` (1,40) et
    `h_sup_50` (1,50) tombaient aussi à 1,30. Les cinq catégories sont donc
    exercées ensemble, sur des heures différentes pour que leurs
    contributions ne puissent pas se confondre."""
    tenant = _societe_avec_paie("PAY-FERIE-2")
    valideur = django_user_model.objects.create_user(
        email="valideur.cinq@example.com", password="Str0ngPassw0rd!23"
    )
    # (catégorie, heures, multiplicateur attendu) — dates distinctes, aucune
    # fériée sauf celle qui doit l'être.
    bareme = [
        ("h_sup_30", Decimal("1"), Decimal("1.30"), dt.date(2026, 3, 2)),
        ("h_sup_50", Decimal("2"), Decimal("1.50"), dt.date(2026, 3, 3)),
        ("nuit", Decimal("3"), Decimal("1.30"), dt.date(2026, 3, 4)),
        ("dimanche", Decimal("4"), Decimal("1.40"), dt.date(2026, 3, 8)),
        ("ferie", Decimal("5"), Decimal("2.00"), dt.date(2026, 3, 16)),
    ]
    with use_tenant(tenant.id):
        declare_holiday(tenant, date=dt.date(2026, 3, 16), name="Journée électorale")
        employe = PrsEmployeeFactory(tenant=tenant)
        for categorie, heures, _mult, date in bareme:
            ligne = record_overtime(employe, date=date, hours=heures, rate_category=categorie)
            validate_overtime(ligne, valideur)

        contract = make_active_contract(tenant, employee_id=employe.id, wage_base=SALAIRE_BASE)
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employe.id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        montant = _ligne(payslip, "HEURES_SUP")

    attendu = sum(h * m * TAUX_HORAIRE for _c, h, m, _d in bareme)
    tout_a_130 = sum(h for _c, h, _m, _d in bareme) * Decimal("1.30") * TAUX_HORAIRE
    assert montant == attendu, (
        f"{montant} Ar au lieu de {attendu} Ar. La valeur {tout_a_130} correspondrait "
        "à l'ancien repli qui imputait TOUTES les catégories à `h_sup_30`."
    )
    assert attendu != tout_a_130, "Barème mal choisi : les deux calculs coïncident."
