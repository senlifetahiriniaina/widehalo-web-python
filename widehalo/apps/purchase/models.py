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
    # Reference opaque vers `apps.stocks.StkWarehouse` (regle de couplage
    # n°1 — jamais de FK Django vers une autre app metier). Depuis la
    # decision P2 (cahier Phase 3 §12.1), c'est une precondition REELLE de
    # la reception : `purchase.services.receiving.receive_order_line`
    # refuse si aucun entrepot valide (avec au moins un emplacement
    # interne) n'est renseigne ici — plus une simple metadonnee
    # informative comme avant que `stocks` n'existe.
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
    # PUR-BUD1 (PU6, cf. plan) : quand renseigne, `services/orders.py::
    # ensure_purchase_approval` compare le cumul reel + cette commande au
    # budget approuve de cet axe analytique (`accounting.services.public.
    # get_budget_variance_for_analytic_account`) et exige une approbation
    # supplementaire en cas de depassement.
    analytic_account_id = models.UUIDField(null=True, blank=True)
    # RG-PUR-7 (importation, PU6, cf. plan) : **stub honnete documente**.
    # Positionne automatiquement a `True` par `services/orders.py::
    # create_order` quand `origin != ORIGIN_LOCAL` — signale qu'un dossier
    # d'importation (transitaire, douane, documents d'expedition) reste a
    # ouvrir. La creation reelle de ce dossier appartient au futur module
    # `logistics` (§5.7.5), pas encore construit dans ce depot : ce champ
    # n'est qu'un drapeau visible, jamais une vraie gestion de dossier.
    import_dossier_pending = models.BooleanField(default=False)
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


class PurReceiptLine(BaseModel):
    """Evenement de reception (RG-PUR-5, §5.6.5, PU5 du sous-sequencement
    `purchase` — cf. plan) : une ligne de commande (`PurOrderLine`) peut
    etre recue en PLUSIEURS livraisons partielles, chacune avec son propre
    controle qualite — un `PurReceiptLine` par reception, jamais un champ
    `quality_status` unique sur `PurOrderLine` qui perdrait l'historique
    (l'ecart RG-PUR-5 doit rester tracable reception par reception, pas
    seulement au global). `BaseModel` sans `ReferenceMixin` : c'est un
    evenement rattache a une commande deja sequencee (`PurOrder.reference`),
    pas lui-meme un document a numeroter — meme discipline que les autres
    lignes de ce module (`PurOrderLine`, `PurRfqResponseLine`...).

    Decision PU5 documentee (cf. plan) : PAS de modele `PurReceipt`
    (en-tete) separe a ce stade — le seul point d'entree de reception
    demande par le CDC/l'API (`POST /orders/{id}/lines/{line_id}/receive`,
    §5.6.6) est PAR LIGNE, jamais un flux "recevoir plusieurs lignes en un
    seul bon" ; le CDC ne fournit non plus aucun numero de bon de livraison
    fournisseur a porter sur un en-tete. Un `PurReceipt` regrouperait donc
    des `PurReceiptLine` crees par des appels SEPARES a `receive_order_line`
    sans qu'aucune information supplementaire ne soit disponible pour le
    construire utilement des maintenant. Le futur rapport PDF bilingue "bon
    de reception" (PUR-REC, PU8) pourra grouper les `PurReceiptLine` par
    `order_line__order` et par date sans en-tete persistant ; si un besoin
    reel d'en-tete apparait alors (ex. reference imprimee), il pourra etre
    ajoute sans casser ce modele (simple FK optionnelle supplementaire).

    `photo_document_ids` : liste JSON d'UUID `core.Document`, JAMAIS une FK
    Django/M2M (regle de couplage n°1 — meme si `core.Document` appartient
    au socle, pas a une autre app "metier", le patron d'attachement deja
    etabli dans ce depot, `core.services.documents.store_document`, est
    invoque exclusivement depuis la couche vues avec un `content_object`
    GenericForeignKey resolu au moment de l'upload HTTP ; ce service n'a
    pas acces a une requete HTTP, seulement a des UUID de documents DEJA
    stockes ailleurs — meme discipline que `variant_id`/
    `preferred_supplier_id` : un simple UUID opaque, jamais une FK)."""

    QUALITY_CONFORME = "conforme"
    QUALITY_NON_CONFORME = "non_conforme"
    QUALITY_SOUS_RESERVE = "sous_reserve"
    QUALITY_CHOICES = [
        (QUALITY_CONFORME, "Conforme"),
        (QUALITY_NON_CONFORME, "Non conforme"),
        (QUALITY_SOUS_RESERVE, "Sous reserve"),
    ]

    order_line = models.ForeignKey(
        "PurOrderLine", on_delete=models.CASCADE, related_name="receipt_lines"
    )
    qty_received = models.DecimalField(max_digits=18, decimal_places=4)
    quality_status = models.CharField(max_length=16, choices=QUALITY_CHOICES)
    notes = models.TextField(blank=True)
    photo_document_ids = models.JSONField(default=list, blank=True)
    received_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "pur_receipt_line"

    def __str__(self) -> str:
        return f"{self.order_line_id} - {self.qty_received} ({self.quality_status})"


class PurReorderingRule(BaseModel):
    """RG-PUR-3 (reapprovisionnement automatique, §5.6.2, PU5 du
    sous-sequencement `purchase` — cf. plan) : seuils min/max/multiple par
    variante (et entrepot optionnel). Memes conventions que `PurSubstitute`
    (cf. sa docstring) : donnee de reference/parametrage, `BaseModel` sans
    `ReferenceMixin`, `is_active` du socle porte a la fois le soft-delete
    standard et le sens metier "regle actuellement active" — pas de second
    champ dedie.

    `variant_id`/`warehouse_id` sont de simples UUID opaques (regle de
    couplage n°1 — jamais de FK Django vers `apps.catalog`) ; `warehouse_id`
    reste nullable et opaque des maintenant car `stocks`/`logistics`
    n'existent pas encore (meme discipline que `PurOrder.warehouse_id`,
    PU3+PU4). La comparaison "stock disponible" reellement exigee par le
    CDC n'est PAS calculee ici (`stocks` n'existe pas) — cf. `services/
    reordering.py::run_reordering` pour le stub documente (stock toujours
    considere a zero, jamais un faux negatif qui ferait perdre un vrai
    besoin)."""

    variant_id = models.UUIDField()
    warehouse_id = models.UUIDField(null=True, blank=True)
    min_qty = models.DecimalField(max_digits=18, decimal_places=4)
    max_qty = models.DecimalField(max_digits=18, decimal_places=4)
    # Les quantites de reapprovisionnement generees doivent arrondir au
    # multiple superieur de cette valeur (ex. conditionnement par carton de
    # 12) — cf. `services/reordering.py::_round_up_to_multiple`.
    multiple_qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    lead_time_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pur_reordering_rule"
        permissions = [
            ("run_reordering", "Peut declencher le reapprovisionnement automatique (RG-PUR-3)"),
        ]

    def __str__(self) -> str:
        return f"{self.variant_id} (min={self.min_qty}, max={self.max_qty})"


class PurCra(BaseModel, ReferenceMixin):
    """Compte rendu d'activite achats (§5.6.2, PU7 du sous-sequencement
    `purchase` — cf. plan) : temps passe par un acheteur sur une activite
    d'achat (sourcing, negociation, relance, visite fournisseur, audit),
    circuit de validation `draft -> submitted -> validated/rejected`.

    **Pas de mutualisation avec `apps.mrp.models.MrpCra`** malgre le nom
    identique : le CDC decrit deux entites `pur_cra`/`mrp_cra` aux champs
    fondamentalement differents (ici pas de notion d'atelier/ordre de
    fabrication, mais un fournisseur et un type d'activite commerciale) —
    a la difference de RG-PUR-8 (evaluation fournisseur), le CDC ne demande
    PAS de mutualisation ici. Meme discipline de workflow que `MrpCra`
    (`draft -> submitted -> validated/rejected`), mais reimplementee en
    CharField simple + garde-fous de service (pas de FSM `django-fsm`,
    memes 2 transitions terminales triviales que `PurRequisition`, cf. sa
    docstring — jamais de branche/permission complexe ici)."""

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_VALIDATED = "validated"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SUBMITTED, "Soumis"),
        (STATE_VALIDATED, "Valide"),
        (STATE_REJECTED, "Rejete"),
    ]

    TYPE_SOURCING = "sourcing"
    TYPE_NEGOCIATION = "negociation"
    TYPE_RELANCE = "relance"
    TYPE_VISITE = "visite"
    TYPE_AUDIT = "audit"
    ACTIVITY_TYPE_CHOICES = [
        (TYPE_SOURCING, "Sourcing"),
        (TYPE_NEGOCIATION, "Negociation"),
        (TYPE_RELANCE, "Relance"),
        (TYPE_VISITE, "Visite fournisseur"),
        (TYPE_AUDIT, "Audit"),
    ]

    date = models.DateField()
    buyer = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1) — un fournisseur est reference par son UUID.
    partner_id = models.UUIDField()
    activity_type = models.CharField(max_length=16, choices=ACTIVITY_TYPE_CHOICES)
    hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    # `PurOrder` appartient au meme app `purchase` — vraie FK Django
    # autorisee (la regle de couplage n1 n'interdit que les FK vers
    # D'AUTRES apps metier).
    order = models.ForeignKey(
        PurOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="cra_entries"
    )
    comment = models.TextField(blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = "pur_cra"

    def __str__(self) -> str:
        return self.reference or f"CRA {self.buyer_id} {self.date}"


class PurCri(BaseModel, ReferenceMixin):
    """Compte rendu d'incident achats (§5.6.2, PU7 du sous-sequencement
    `purchase` — cf. plan) : incident fournisseur trace (retard, non
    conformite, litige, rupture, incident douanier) avec impact/action
    corrective/cout chiffre.

    **Distinct de `PurOrder.open_dispute`/`dispute_reason`** (PU4, branche
    FSM "en litige") : cette derniere ne fait qu'ouvrir un ETAT sur LA
    commande elle-meme (un seul champ texte, pas de suivi cout/impact/
    action) — `PurCri` est l'entite riche demandee par le CDC (`pur_cri`),
    avec son propre cycle de vie `draft -> closed`, potentiellement SANS
    commande rattachee (ex. rupture de stock chez un fournisseur avant
    toute commande passee). `record_supplier_invoice` (PU6,
    `services/invoicing.py`) cree desormais AUSSI un `PurCri` de type
    `litige` en plus d'`open_order_dispute`, cf. docstring de ce service —
    les deux mecanismes cohabitent sciemment.

    **Pas de mutualisation avec `apps.mrp.models.MrpCri`** : memes raisons
    que `PurCra` ci-dessus — champs fondamentalement differents (cout
    chiffre, impact, fournisseur, jamais d'atelier/poste de charge)."""

    TYPE_RETARD = "retard"
    TYPE_NON_CONFORMITE = "non_conformite"
    TYPE_LITIGE = "litige"
    TYPE_RUPTURE = "rupture"
    TYPE_INCIDENT_DOUANE = "incident_douane"
    TYPE_CHOICES = [
        (TYPE_RETARD, "Retard"),
        (TYPE_NON_CONFORMITE, "Non conformite"),
        (TYPE_LITIGE, "Litige"),
        (TYPE_RUPTURE, "Rupture"),
        (TYPE_INCIDENT_DOUANE, "Incident douanier"),
    ]

    STATE_DRAFT = "draft"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_DRAFT, "Ouvert"),
        (STATE_CLOSED, "Cloture"),
    ]

    date = models.DateField()
    type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    # Jamais de FK Django vers `apps.partners.models.Partner`.
    partner_id = models.UUIDField()
    order = models.ForeignKey(
        PurOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="cri_entries"
    )
    description = models.TextField()
    impact = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)
    cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Liste JSON d'UUID `core.Document`, JAMAIS une FK Django/M2M — meme
    # patron que `PurReceiptLine.photo_document_ids` (PU5, cf. sa
    # docstring pour le raisonnement complet).
    attachment_document_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "pur_cri"

    def __str__(self) -> str:
        return self.reference or f"CRI {self.type} {self.partner_id}"


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


class PrcPriceWatchTarget(BaseModel):
    """Veille prix fournisseurs Chine/Europe (PRC1-3, chantier « etudes de
    faisabilite, veille prix fournisseurs, capacite 90j, risques
    operationnels, qualite/certification, refonte UI/UX » — cf. plan,
    sous-section « 2. Veille prix fournisseurs Chine/Europe »).

    **Reserve de securite/legalite (decision deja actee, non
    negociable)** : ce modele ne stocke qu'une CIBLE de veille (plateforme
    + requete/URL de recherche) — AUCUN scraping HTTP reel n'est declenche
    par sa seule creation. Le mecanisme d'observation reel/interchangeable
    vit dans `services/price_watch.py` (cf. sa docstring de tete pour le
    detail complet de cette reserve) : par defaut, `StubPriceSourceProvider`
    est utilise pour TOUTE plateforme (aucun appel reseau), et
    `PrcPriceSnapshot.is_stub=True` en decoule systematiquement tant
    qu'aucun connecteur reel n'est explicitement configure par
    l'utilisateur via `settings.PRICE_WATCH_PROVIDERS`.

    **Reference produit UUID nue, jamais de FK Django** (regle de couplage
    n°1, identique a `PurOrderLine.variant_id`/`PurReorderingRule.
    variant_id` ci-dessus) : `material_reference_id` peut pointer vers
    `apps.catalog.models.CatalogMaterialReference` (referentiel de
    matieres, chantier LIFE MDG precedent) et `variant_id` vers
    `apps.catalog.models.ProductVariant` — `purchase` ne doit JAMAIS
    importer `apps.catalog.models` pour autant. Exactement UN des deux
    doit etre renseigne (jamais les deux, jamais aucun) : invariant
    valide par `services/price_watch.py::create_price_watch_target`,
    jamais au niveau modele (une contrainte `CheckConstraint` XOR sur deux
    `UUIDField` nullable serait plus fragile a faire evoluer qu'une
    validation service explicite, meme discipline que le reste de ce
    depot pour les invariants multi-champs)."""

    PLATFORM_ALIBABA = "alibaba"
    PLATFORM_1688 = "1688"
    PLATFORM_ALIEXPRESS = "aliexpress"
    PLATFORM_EUROPAGES = "europages"
    PLATFORM_KOMPASS = "kompass"
    PLATFORM_AUTRE = "autre"
    PLATFORM_CHOICES = [
        (PLATFORM_ALIBABA, "Alibaba"),
        (PLATFORM_1688, "1688.com"),
        (PLATFORM_ALIEXPRESS, "AliExpress"),
        (PLATFORM_EUROPAGES, "Europages"),
        (PLATFORM_KOMPASS, "Kompass"),
        (PLATFORM_AUTRE, "Autre"),
    ]

    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_QUARTERLY = "quarterly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_MONTHLY, "Mensuelle"),
        (FREQUENCY_QUARTERLY, "Trimestrielle"),
    ]

    material_reference_id = models.UUIDField(null=True, blank=True)
    variant_id = models.UUIDField(null=True, blank=True)
    platform_code = models.CharField(max_length=16, choices=PLATFORM_CHOICES)
    search_query_or_url = models.TextField()
    currency = models.CharField(max_length=8, default="MGA")
    frequency = models.CharField(
        max_length=16, choices=FREQUENCY_CHOICES, default=FREQUENCY_MONTHLY
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_price_watch_target"
        permissions = [
            (
                "run_price_watch_check",
                "Peut declencher manuellement une verification de veille prix (PRC1-3)",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_platform_code_display()} - {self.search_query_or_url[:40]}"


class PrcPriceSnapshot(BaseModel):
    """Releve de prix observe pour une `PrcPriceWatchTarget` donnee
    (PRC1-3, cf. docstring de `PrcPriceWatchTarget` ci-dessus pour la
    reserve de securite complete). `is_stub=True` tant que le provider
    actif pour `target.platform_code` est `StubPriceSourceProvider`
    (defaut systeme, cf. `services/price_watch.py::get_provider_for_
    platform`) — un releve `is_stub=False` suppose qu'un connecteur reel
    a ete explicitement configure par l'utilisateur, jamais un defaut de
    ce chantier."""

    target = models.ForeignKey(
        PrcPriceWatchTarget, on_delete=models.CASCADE, related_name="snapshots"
    )
    observed_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    observed_at = models.DateTimeField()
    source_note = models.TextField(blank=True)
    is_stub = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_price_snapshot"
        ordering = ["-observed_at"]

    def __str__(self) -> str:
        return f"{self.target_id} - {self.observed_at:%Y-%m-%d}"
