"""Service de facturation multi-modes du module `projects` (PJ5) — cf.
plan, section « Module `projects` », etape PJ5. Comble le gap explicitement
annonce depuis PJ1 dans la docstring de `models.py` : jusqu'ici,
`client_partner_id`/`accounting.services.public.
create_customer_invoice_from_source` n'etaient jamais consommes.

**4 modes de facturation**, chacun refusant explicitement (jamais une
creation silencieuse suivie d'un crash ailleurs) toute condition
prealable manquante :

1. `bill_by_milestone` : le montant CONTRACTUEL d'un jalon (`PrjTask.
   budgeted_amount`, cf. docstring de ce champ dans `models.py` pour la
   decision de conception) une fois celui-ci `state=done`. Une seule
   facturation par jalon (verifiee par `PrjInvoicingRecord.objects.filter(
   task=task, mode=MODE_MILESTONE)`).
2. `bill_by_percentage` : facturation INCREMENTALE de l'ecart entre l'`EV`
   (Earned Value, deja calcule par `services/evm.py::compute_evm_snapshot`
   — reutilise tel quel, AUCUNE reimplementation du calcul d'avancement
   pondere ici) et le total DEJA facture par ce mode pour ce projet
   (somme des `PrjInvoicingRecord.amount` de mode `percentage`). Refuse
   explicitement si l'ecart est nul/negatif (rien de nouveau a facturer —
   ex. l'avancement n'a pas progresse depuis la derniere facturation, ou a
   regresse suite a une correction).
3. `bill_time_and_material` : **COMPLETE A PJ8** (etait un STUB HONNETE
   depuis PJ5, `TimeAndMaterialNotImplementedError`, en attendant
   `PrjTimeEntry`). Facture `services/time_tracking.py::get_unbilled_
   billable_hours(project) x hourly_rate` — reutilise directement ce
   service (aucune reimplementation de l'agregation du temps ici). Refuse
   explicitement (`ValidationError`) si le nombre d'heures facturables non
   facturees est nul (rien de nouveau a facturer). Marque les
   `PrjTimeEntry` facturables non facturees de ce projet `billed=True`
   **APRES** le succes confirme de la creation de facture (jamais avant,
   meme discipline que `PrjInvoicingRecord` cf. discipline commune
   ci-dessous) — si la facture n'est pas creee (config comptable
   incomplete), AUCUNE entree n'est marquee `billed=True`. L'ancienne
   `TimeAndMaterialNotImplementedError` (stub PJ5) est retiree de ce
   fichier — plus aucun appelant (`api.py`/`views.py`/tests) n'en depend,
   verifie explicitement avant suppression (l'endpoint `POST .../bill/
   time-and-material` renvoie desormais 200 en cas de succes, comme les 3
   autres modes, jamais plus 501).
4. `bill_fixed` : un montant fixe SAISI MANUELLEMENT, une seule fois par
   projet (verifie par `PrjInvoicingRecord.objects.filter(project=project,
   mode=MODE_FIXED)`).

**Discipline commune aux 4 modes** (factorisee dans `_create_invoice_and_
record`) :
- refuse (leve `ValidationError`) si `project.client_partner_id` n'est pas
  renseigne — JAMAIS de facture sans client identifie ;
- construit `income_lines` au format EXACT attendu par
  `accounting.services.public.create_customer_invoice_from_source`
  (verifie dans le code reel de ce fichier, pas devine) : une liste de
  `{"account_id": UUID | None, "amount": Decimal, "label": str}` —
  `account_id=None` ici (V1) : `projects` ne connait/ne resout aucun
  compte de produit specifique, il retombe sur le compte de produit par
  defaut du tenant resolu par le gap lui-meme (jamais un code de compte
  invente ici, encore moins un code OHADA en dur — ce depot est en PCG
  2005 malgache) ;
- gere le retour `None` du gap EXPLICITEMENT : leve `ValidationError`
  avec un message clair a l'utilisateur ("configuration comptable du
  tenant incomplete"), ne cree JAMAIS de `PrjInvoicingRecord` dans ce cas
  (pas de trace de facturation pour une facture qui n'existe pas) ;
- ne cree la trace de facturation (`PrjInvoicingRecord`) QU'APRES le
  succes confirme de la creation de facture (jamais avant, jamais en cas
  d'echec) — evite toute double-facturation ulterieure basee sur une trace
  fantome."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_customer_invoice_from_source
from apps.core.models.user import User
from apps.projects.models import PrjInvoicingRecord, PrjProject, PrjTask, PrjTimeEntry
from apps.projects.services.evm import compute_evm_snapshot
from apps.projects.services.time_tracking import get_unbilled_billable_hours

_MONEY_QUANT = Decimal("0.0001")


def _ensure_client_partner(project: PrjProject) -> UUID:
    if project.client_partner_id is None:
        raise ValidationError(_("Le projet n'a pas de client identifie : facturation impossible."))
    return project.client_partner_id


def _create_invoice_and_record(
    project: PrjProject,
    *,
    mode: str,
    amount: Decimal,
    label: str,
    user: User,
    task: PrjTask | None = None,
    date: dt.date | None = None,
) -> UUID:
    """Factorise la discipline commune aux 4 modes — cf. docstring de
    module. Retourne l'UUID de la facture `accounting` creee (toujours en
    `draft`, jamais auto-validee — decision assumee par le gap lui-meme,
    cf. docstring de `create_customer_invoice_from_source`)."""
    partner_id = _ensure_client_partner(project)
    billed_date = date or timezone.now().date()
    invoice_id = create_customer_invoice_from_source(
        tenant=project.tenant,
        partner_id=partner_id,
        date=billed_date,
        income_lines=[{"account_id": None, "amount": amount, "label": label}],
    )
    if invoice_id is None:
        raise ValidationError(
            _(
                "Configuration comptable du tenant incomplete "
                "(journal de vente/periode ouverte/compte client ou "
                "produit manquant) : aucune facture n'a ete generee."
            )
        )
    PrjInvoicingRecord.objects.create(
        tenant=project.tenant,
        project=project,
        task=task,
        mode=mode,
        amount=amount,
        invoice_id=invoice_id,
        billed_date=billed_date,
        billed_by=user,
    )
    return invoice_id


def bill_by_milestone(project: PrjProject, task: PrjTask, user: User) -> UUID:
    """Cf. docstring de module, point 1."""
    if task.project_id != project.id:
        raise ValidationError(_("La tache ne fait pas partie de ce projet."))
    if task.task_type != PrjTask.TYPE_MILESTONE:
        raise ValidationError(_("Seul un jalon peut etre facture par ce mode."))
    if task.state != PrjTask.STATE_DONE:
        raise ValidationError(_("Le jalon doit etre termine avant de pouvoir etre facture."))
    if task.budgeted_amount is None:
        raise ValidationError(
            _("Ce jalon n'a pas de montant budgetise renseigne (PrjTask.budgeted_amount).")
        )
    already_billed = PrjInvoicingRecord.objects.filter(
        task=task, mode=PrjInvoicingRecord.MODE_MILESTONE, is_active=True
    ).exists()
    if already_billed:
        raise ValidationError(_("Ce jalon a deja ete facture."))
    label = _("Facturation du jalon %(reference)s") % {"reference": task.reference or task.id}
    return _create_invoice_and_record(
        project,
        mode=PrjInvoicingRecord.MODE_MILESTONE,
        amount=task.budgeted_amount,
        label=str(label),
        user=user,
        task=task,
    )


def bill_by_percentage(project: PrjProject, user: User) -> UUID:
    """Cf. docstring de module, point 2 — reutilise `compute_evm_snapshot`
    (PJ4) pour l'`EV`, aucune reimplementation de l'arithmetique
    d'avancement pondere ici."""
    snapshot = compute_evm_snapshot(project)
    if snapshot.ev is None:
        raise ValidationError(
            _(
                "Avancement non calculable pour ce projet (aucune tache "
                "active ou aucune ligne budgetaire) : facturation impossible."
            )
        )
    already_billed = PrjInvoicingRecord.objects.filter(
        project=project, mode=PrjInvoicingRecord.MODE_PERCENTAGE, is_active=True
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    incremental = (snapshot.ev - already_billed).quantize(_MONEY_QUANT)
    if incremental <= 0:
        raise ValidationError(
            _(
                "Rien a facturer : l'avancement facturable n'a pas "
                "progresse depuis la derniere facturation par avancement."
            )
        )
    label = _("Facturation a l'avancement (%(pct)s de BAC deja facture cumule)") % {
        "pct": snapshot.ev
    }
    return _create_invoice_and_record(
        project,
        mode=PrjInvoicingRecord.MODE_PERCENTAGE,
        amount=incremental,
        label=str(label),
        user=user,
    )


def bill_time_and_material(project: PrjProject, user: User, *, hourly_rate: Decimal) -> UUID:
    """Cf. docstring de module, point 3 — reutilise `services/time_
    tracking.py::get_unbilled_billable_hours` (aucune reimplementation de
    l'agregation du temps ici)."""
    if hourly_rate <= 0:
        raise ValidationError(_("Le taux horaire doit etre strictement positif."))
    unbilled_hours = get_unbilled_billable_hours(project)
    if unbilled_hours <= 0:
        raise ValidationError(
            _("Rien a facturer : aucune heure facturable non encore facturee sur ce projet.")
        )
    amount = (unbilled_hours * hourly_rate).quantize(_MONEY_QUANT)
    label = _("Facturation en regie (%(hours)s heures x %(rate)s)") % {
        "hours": unbilled_hours,
        "rate": hourly_rate,
    }
    # Selectionne AVANT la creation de facture (le montant facture doit
    # correspondre EXACTEMENT aux entrees marquees `billed=True` ensuite) —
    # `list(...)` fige la liste d'ids avant tout risque de course avec une
    # nouvelle entree creee entre-temps.
    unbilled_entry_ids = list(
        PrjTimeEntry.objects.filter(
            task__project=project,
            is_active=True,
            stopped_at__isnull=False,
            billable=True,
            billed=False,
        ).values_list("id", flat=True)
    )
    invoice_id = _create_invoice_and_record(
        project,
        mode=PrjInvoicingRecord.MODE_TIME_AND_MATERIAL,
        amount=amount,
        label=str(label),
        user=user,
    )
    PrjTimeEntry.objects.filter(id__in=unbilled_entry_ids).update(billed=True)
    return invoice_id


def bill_fixed(project: PrjProject, user: User, *, amount: Decimal) -> UUID:
    """Cf. docstring de module, point 4."""
    if amount <= 0:
        raise ValidationError(_("Le montant forfaitaire doit etre strictement positif."))
    already_billed = PrjInvoicingRecord.objects.filter(
        project=project, mode=PrjInvoicingRecord.MODE_FIXED, is_active=True
    ).exists()
    if already_billed:
        raise ValidationError(_("Ce projet a deja fait l'objet d'une facturation forfaitaire."))
    label = _("Facturation forfaitaire du projet %(reference)s") % {
        "reference": project.reference or project.id
    }
    return _create_invoice_and_record(
        project,
        mode=PrjInvoicingRecord.MODE_FIXED,
        amount=amount,
        label=str(label),
        user=user,
    )
