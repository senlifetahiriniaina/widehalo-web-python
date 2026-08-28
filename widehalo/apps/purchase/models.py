"""Achats (§5.6, PU1 du sous-sequencement `purchase` — cf. plan) : demande
d'achat (`PurRequisition`/`PurRequisitionLine`), premiere brique du
module. Workflow simple `draft -> submitted -> approved/rejected` (pas de
FSM `django-fsm` a ce stade : deux transitions terminales triviales, meme
discipline que `AccBudget`/`AccLandedCostBatch` — la FSM complete
§5.6.4 n'arrive qu'en PU4 sur `PurOrder`). La resolution de prix indicative
par ligne (`estimated_price_mga`) passe par
`apps.catalog.services.public.get_variant_price`, meme patron que
`sales.services.quotations.add_quotation_line` (S1).

Regle de couplage n1 (identique a `sales`/`crm`/`mrp`) : `purchase` ne fait
jamais de FK Django vers `apps.catalog`/`apps.partners` (ni, plus tard,
`apps.mrp`/`apps.accounting`) — ces entites sont referencees par UUID nu,
resolues via `services.public` de chaque app quand une information
affichable est necessaire. Le seul FK "reel" est vers `core.User`
(demandeur), qui appartient au socle et n'est pas une autre app metier."""

from __future__ import annotations

from django.db import models
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin


class PurRequisition(BaseModel, ReferenceMixin):
    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_APPROVED = "approved"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SUBMITTED, "Soumise"),
        (STATE_APPROVED, "Approuvee"),
        (STATE_REJECTED, "Rejetee"),
    ]

    requester = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    department = models.CharField(max_length=100, blank=True)
    date_needed = models.DateField()
    justification = models.TextField(blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Reference libre vers un document d'origine (ex. un devis, un besoin de
    # production) — pas de generic FK a ce stade, hors perimetre PU1.
    source_document = models.CharField(max_length=255, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = "pur_requisition"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class PurRequisitionLine(BaseModel):
    requisition = models.ForeignKey(PurRequisition, on_delete=models.CASCADE, related_name="lines")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — un
    # article est reference par son UUID, resolu via `catalog.services.public`.
    variant_id = models.UUIDField()
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    estimated_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Jamais de FK Django vers `apps.partners.models.Partner` — un tiers est
    # reference par son UUID uniquement (resolu automatiquement via
    # `catalog.services.public.select_preferred_supplier` quand non fourni
    # explicitement, cf. `services/requisitions.py`, RG-PUR-1/PU2).
    preferred_supplier_id = models.UUIDField(null=True, blank=True)
    # RG-PUR-2 (substitution) : `PurSubstitute` appartient au meme app
    # `purchase` — une vraie FK Django est donc autorisee ici (la regle de
    # couplage n1 n'interdit que les FK VERS D'AUTRES apps metier).
    substitute = models.ForeignKey(
        "PurSubstitute", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "pur_requisition_line"

    def __str__(self) -> str:
        return f"{self.requisition_id} - {self.description}"


class PurSubstitute(BaseModel):
    """RG-PUR-2 (substitution, PU2 du sous-sequencement `purchase`, cf.
    plan) : proposition de remplacement d'un article par un autre, classee
    par niveau de compatibilite. Donnee de reference/parametrage (pas un
    document sequence) — memes conventions que `AccTax`/`CrmLostReason` :
    `BaseModel` sans `ReferenceMixin`.

    `variant_id`/`substitute_variant_id` sont de simples UUID, JAMAIS une
    FK Django vers `apps.catalog.models.ProductVariant` (regle de couplage
    n°1). `is_active` (fourni par `BaseModel`, cf. sa docstring) porte a la
    fois le soft-delete standard et le sens metier "substitut actuellement
    propose" — un seul champ, pas de doublon, meme discipline que les
    autres modeles de reference du socle (ex. `PatGradingRule`).

    Une substitution `degrade` exige une validation avant d'etre utilisable
    (`ensure_substitute_usable`) — cf. `services/substitution.py`, meme
    patron `ApprovalRule`/`ApprovalRequest` qu'`crm.services.discounts`."""

    COMPATIBILITY_IDENTIQUE = "identique"
    COMPATIBILITY_EQUIVALENT = "equivalent"
    COMPATIBILITY_DEGRADE = "degrade"
    COMPATIBILITY_CHOICES = [
        (COMPATIBILITY_IDENTIQUE, "Identique"),
        (COMPATIBILITY_EQUIVALENT, "Equivalent"),
        (COMPATIBILITY_DEGRADE, "Degrade"),
    ]

    variant_id = models.UUIDField()
    substitute_variant_id = models.UUIDField()
    compatibility = models.CharField(max_length=16, choices=COMPATIBILITY_CHOICES)
    # Ratio de conversion si les quantites different (ex. 1.2 unite de
    # substitut pour 1 unite d'origine).
    ratio = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    # Texte libre i18n-able (traduction geree au niveau presentation, pas
    # de machinerie i18n dediee — meme discipline que `justification`/
    # `comment` ailleurs dans ce depot).
    conditions = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "pur_substitute"

    def __str__(self) -> str:
        return f"{self.variant_id} -> {self.substitute_variant_id} ({self.compatibility})"


def _default_award_criteria() -> dict[str, float]:
    """RG-PUR-4 : ponderation par defaut du tableau comparatif (`services/
    rfq.py::compute_comparison_table`) — modifiable par appel d'offres.
    `quality` n'a aucune source numerique dans ce modele (aucune evaluation
    fournisseur n'est encore rattachee a une reponse d'appel d'offres, cf.
    docstring de `compute_comparison_table`) : le poids existe pour que le
    tenant puisse deja parametrer l'intention, mais son critere reste neutre
    tant que ce gap n'est pas comble."""
    return {"price": 0.5, "delay": 0.3, "quality": 0.2}


class PurRfq(BaseModel, ReferenceMixin):
    """Appel d'offres (RG-PUR-4, §5.6.3, PU3+PU4 du sous-sequencement
    `purchase` — cf. plan) : consultation a N fournisseurs (`PurRfqSupplier`),
    reponses recues (`PurRfqResponse`/`PurRfqResponseLine`) comparees via un
    tableau pondere (`award_criteria`), attribution manuelle qui genere une
    vraie `PurOrder` (jamais d'attribution automatique — cf.
    `services/rfq.py::award_rfq`).

    Workflow simple `draft -> sent -> closed`/`awarded` (pas de FSM
    `django-fsm` : peu d'etats triviaux et lineaires, meme discipline que
    `PurRequisition`, cf. sa docstring — la FSM complete §5.6.4 ne concerne
    que `PurOrder`)."""

    STATE_DRAFT = "draft"
    STATE_SENT = "sent"
    STATE_CLOSED = "closed"
    STATE_AWARDED = "awarded"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SENT, "Envoye"),
        (STATE_CLOSED, "Cloture"),
        (STATE_AWARDED, "Attribue"),
    ]

    date = models.DateField()
    deadline = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Ponderation du tableau comparatif — cf. `_default_award_criteria`.
    award_criteria = models.JSONField(default=_default_award_criteria)

    class Meta:
        db_table = "pur_rfq"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class PurRfqLine(BaseModel):
    rfq = models.ForeignKey(PurRfq, on_delete=models.CASCADE, related_name="lines")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` (regle
    # de couplage n1) — un article est reference par son UUID.
    variant_id = models.UUIDField()
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "pur_rfq_line"

    def __str__(self) -> str:
        return f"{self.rfq_id} - {self.description}"


class PurRfqSupplier(BaseModel):
    """Fournisseur consulte pour un appel d'offres — modele "through" a la
    place d'un `ManyToManyField` nu, car `partner_id` doit rester un simple
    UUID (jamais une FK Django vers `apps.partners.models.Partner`, regle de
    couplage n1) : un `ManyToManyField` de Django exige une FK reelle des
    deux cotes, incompatible avec cette regle."""

    rfq = models.ForeignKey(PurRfq, on_delete=models.CASCADE, related_name="suppliers")
    partner_id = models.UUIDField()

    class Meta:
        db_table = "pur_rfq_supplier"
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "partner_id"], name="uniq_pur_rfq_supplier_rfq_partner"
            )
        ]

    def __str__(self) -> str:
        return f"{self.rfq_id} - {self.partner_id}"


class PurRfqResponse(BaseModel):
    rfq = models.ForeignKey(PurRfq, on_delete=models.CASCADE, related_name="responses")
    partner_id = models.UUIDField()
    date_received = models.DateField()
    total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    currency = models.CharField(max_length=3, default="MGA")
    lead_time_days = models.PositiveIntegerField(default=0)
    validity_date = models.DateField(null=True, blank=True)
    # Calcule par `services/rfq.py::compute_comparison_table`, jamais saisi
    # directement — reste `None` tant que le tableau comparatif n'a pas ete
    # calcule au moins une fois pour cet appel d'offres.
    score = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "pur_rfq_response"

    def __str__(self) -> str:
        return f"{self.rfq_id} - {self.partner_id}"


class PurRfqResponseLine(BaseModel):
    response = models.ForeignKey(PurRfqResponse, on_delete=models.CASCADE, related_name="lines")
    variant_id = models.UUIDField()
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    unit_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "pur_rfq_response_line"

    def __str__(self) -> str:
        return f"{self.response_id} - {self.variant_id}"


class PurOrder(BaseModel, ReferenceMixin):
    """Commande d'achat (§5.6.4, PU3+PU4 du sous-sequencement `purchase` —
    cf. plan) : machine a etats complete (`django-fsm-2`, `attempt_transition()`
    du socle — jamais un appel direct a une methode `@transition`, meme
    discipline que `SalesOrder`/`AccMove.invoice_state`).

    Le diagramme du CDC decrit un cycle en une seule chaine (brouillon -> a
    valider -> validee -> envoyee -> confirmee -> en transit -> recue
    partiellement -> recue -> facturee -> cloturee, avec deux branches
    annulee/en litige) : un seul champ FSM suffit, meme simplification
    assumee que `SalesOrder.state` (cf. sa docstring) — jamais 3 statuts
    croises pour un cycle de vie fondamentalement lineaire.

    Peut naitre de 3 facons : creation directe, depuis une/plusieurs
    `PurRequisition` approuvees (`services/orders.py::create_order_from_
    requisition`/`create_bulk_orders_from_requisitions`, PUR-BULK1), ou par
    attribution d'un appel d'offres (`services/rfq.py::award_rfq`,
    RG-PUR-4) — `requisition`/`rfq` restent tous deux nullables et ne
    s'excluent pas mutuellement au niveau du modele (le service d'attribution
    ne renseigne que `rfq`, mais rien n'empeche un usage futur combinant les
    deux)."""

    STATE_DRAFT = "draft"
    STATE_TO_VALIDATE = "to_validate"
    STATE_VALIDATED = "validated"
    STATE_SENT = "sent"
    STATE_CONFIRMED = "confirmed"
    STATE_IN_TRANSIT = "in_transit"
    STATE_PARTIALLY_RECEIVED = "partially_received"
    STATE_RECEIVED = "received"
    STATE_INVOICED = "invoiced"
    STATE_CLOSED = "closed"
    STATE_CANCELLED = "cancelled"
    STATE_IN_DISPUTE = "in_dispute"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_TO_VALIDATE, "A valider"),
        (STATE_VALIDATED, "Validee"),
        (STATE_SENT, "Envoyee"),
        (STATE_CONFIRMED, "Confirmee"),
        (STATE_IN_TRANSIT, "En transit"),
        (STATE_PARTIALLY_RECEIVED, "Recue partiellement"),
        (STATE_RECEIVED, "Recue"),
        (STATE_INVOICED, "Facturee"),
        (STATE_CLOSED, "Cloturee"),
        (STATE_CANCELLED, "Annulee"),
        (STATE_IN_DISPUTE, "En litige"),
    ]

    # Memes 4 valeurs que `apps.catalog.models.ProductSupplierInfo.origin`
    # (RG-PUR-1, PU2) — constante Python distincte plutot qu'un import (la
    # regle de couplage n1 interdit tout import de modele cross-app, y
    # compris pour reutiliser une simple liste de choix), les chaines
    # doivent rester identiques par convention documentee.
    ORIGIN_LOCAL = "local"
    ORIGIN_IMPORT_CHINE = "import_chine"
    ORIGIN_IMPORT_AUTRE = "import_autre"
    ORIGIN_EN_LIGNE = "en_ligne"
    ORIGIN_CHOICES = [
        (ORIGIN_LOCAL, "Local"),
        (ORIGIN_IMPORT_CHINE, "Import Chine"),
        (ORIGIN_IMPORT_AUTRE, "Import autre"),
        (ORIGIN_EN_LIGNE, "En ligne"),
    ]

    INCOTERM_EXW = "EXW"
    INCOTERM_FOB = "FOB"
    INCOTERM_CIF = "CIF"
    INCOTERM_DAP = "DAP"
    INCOTERM_DDP = "DDP"
    INCOTERM_CHOICES = [
        (INCOTERM_EXW, "EXW — A l'usine"),
        (INCOTERM_FOB, "FOB — Franco a bord"),
        (INCOTERM_CIF, "CIF — Cout, assurance et fret"),
        (INCOTERM_DAP, "DAP — Rendu au lieu de destination"),
        (INCOTERM_DDP, "DDP — Rendu droits acquittes"),
    ]

    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1) — un tiers (fournisseur) est reference par son UUID.
    partner_id = models.UUIDField()
    date = models.DateField()
    date_expected = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    # Jamais de FK Django vers `apps.accounting.models.AccPaymentTerm`.
    payment_term_id = models.UUIDField(null=True, blank=True)
    incoterm = models.CharField(max_length=8, choices=INCOTERM_CHOICES, blank=True)
    origin = models.CharField(max_length=16, choices=ORIGIN_CHOICES, default=ORIGIN_LOCAL)
    state = FSMField(default=STATE_DRAFT, choices=STATE_CHOICES)
    amount_untaxed_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_tax_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Reference opaque a un futur entrepot (`stocks`, pas encore construit)
    # — aucune validation contre ce module tant qu'il n'existe pas.
    warehouse_id = models.UUIDField(null=True, blank=True)
    # `PurRequisition`/`PurRfq` appartiennent au meme app `purchase` — une
    # vraie FK Django est donc autorisee (la regle de couplage n1 n'interdit
    # que les FK vers D'AUTRES apps metier).
    requisition = models.ForeignKey(
        PurRequisition, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    rfq = models.ForeignKey(
        PurRfq, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    # Champ prepare pour le futur gap budgetaire PUR-BUD1 (PU6, cf. plan) —
    # aucune logique cablee ici.
    analytic_account_id = models.UUIDField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    dispute_reason = models.TextField(blank=True)

    class Meta:
        db_table = "pur_order"

    def __str__(self) -> str:
        return self.reference or str(self.id)

    @transition(field=state, source=STATE_DRAFT, target=STATE_TO_VALIDATE)
    def submit_for_validation(self) -> None:
        pass

    # RG-PUR-ROUT1 : le controle de routage d'approbation (`services/
    # orders.py::ensure_purchase_approval`) est verifie par la fonction de
    # service AVANT d'appeler cette transition — jamais dans la methode
    # elle-meme (meme discipline que `AccMove.validate`/`SalesOrder.confirm`,
    # la garde metier reste dans `services/`, la methode `@transition` ne
    # fait que deplacer l'etat).
    @transition(field=state, source=STATE_TO_VALIDATE, target=STATE_VALIDATED)
    def validate(self) -> None:
        pass

    @transition(field=state, source=STATE_VALIDATED, target=STATE_SENT)
    def send(self) -> None:
        pass

    @transition(field=state, source=STATE_SENT, target=STATE_CONFIRMED)
    def confirm(self) -> None:
        pass

    @transition(field=state, source=STATE_CONFIRMED, target=STATE_IN_TRANSIT)
    def mark_in_transit(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_TRANSIT, target=STATE_PARTIALLY_RECEIVED)
    def mark_partially_received(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_IN_TRANSIT, STATE_PARTIALLY_RECEIVED],
        target=STATE_RECEIVED,
    )
    def mark_received(self) -> None:
        pass

    # RG-PUR-6 (controle facture 3 voies) est cablee depuis PU6 — cette
    # transition est declaree des maintenant pour completude de la FSM
    # (meme patron que `SalesOrder.mark_invoiced` declaree en S2 avant
    # d'etre reellement cablee en S4).
    @transition(field=state, source=STATE_RECEIVED, target=STATE_INVOICED)
    def mark_invoiced(self) -> None:
        pass

    @transition(field=state, source=STATE_INVOICED, target=STATE_CLOSED)
    def close(self) -> None:
        pass

    @transition(
        field=state,
        source=[
            STATE_DRAFT,
            STATE_TO_VALIDATE,
            STATE_VALIDATED,
            STATE_SENT,
            STATE_CONFIRMED,
            STATE_IN_TRANSIT,
        ],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass

    # Branche "en litige" : un desaccord fournisseur (livraison, facture...)
    # peut survenir a partir du moment ou la commande est engagee aupres du
    # fournisseur (confirmee) jusqu'a la facturation incluse — jamais avant
    # confirmation (rien a contester tant que le fournisseur n'a rien
    # engage) ni apres cloture (deja soldee).
    @transition(
        field=state,
        source=[
            STATE_CONFIRMED,
            STATE_IN_TRANSIT,
            STATE_PARTIALLY_RECEIVED,
            STATE_RECEIVED,
            STATE_INVOICED,
        ],
        target=STATE_IN_DISPUTE,
    )
    def open_dispute(self) -> None:
        pass

    # Simplification assumee et documentee : quel que soit l'etat d'origine
    # du litige, la resolution ramene toujours la commande a `received` —
    # c'est l'etat pivot du controle facture 3 voies RG-PUR-6 (PU6, la
    # source la plus frequente de litige), et une commande deja facturee ou
    # en transit ne doit de toute facon pas reprendre son cycle normal tant
    # que le desaccord sous-jacent n'est pas retranche/reconcilie. Pas de
    # machine a etats "retour a l'etat precedent" generique dans ce socle.
    @transition(field=state, source=STATE_IN_DISPUTE, target=STATE_RECEIVED)
    def resolve_dispute(self) -> None:
        pass


class PurOrderLine(BaseModel):
    order = models.ForeignKey(PurOrder, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant`.
    variant_id = models.UUIDField()
    supplier_sku = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    unit_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Taux plat, non rattache a `apps.accounting.models.AccTax` — hors
    # perimetre jusqu'au gap facture fournisseur de PU6.
    tax_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    subtotal_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_received = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    date_expected = models.DateField(null=True, blank=True)
    # `PurSubstitute` appartient au meme app `purchase` — vraie FK Django
    # autorisee (meme discipline que `PurRequisitionLine.substitute`, PU2).
    substitute = models.ForeignKey(
        PurSubstitute, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "pur_order_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"
