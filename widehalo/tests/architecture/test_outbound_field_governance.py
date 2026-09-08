"""Garde-fou bloquant — T0, §9.2 : ce que les trois modules ont le droit de
laisser sortir.

Le §9.2 du cahier Phase 4 ne se contente pas d'une intention : trois de ses
six lignes NOMMENT des champs, et une quatrieme interdit un domaine entier
en disant explicitement « verifie en integration continue ». Ce fichier est
cette integration continue.

Ne JAMAIS desactiver ni affaiblir ces tests pour debloquer une liaison
(cf. CONTRIBUTING.md). Un champ qui doit sortir se DECLARE ; un champ
interdit qui gene se rediscute avec le commanditaire, jamais en retirant
une assertion.
"""

from __future__ import annotations

import pytest
from apps.core.services.outbound_schemas import (
    CATEGORIES,
    CATEGORY_COMMERCIAL_DOCUMENT,
    MOTIF_MINIMUM,
    OPERATION_CODES,
    OutboundDocument,
    OutboundField,
    SourceFieldRefusedError,
    get_outbound_document,
    list_outbound_documents,
    project_document,
    validate_source_path,
)
from django.core.exceptions import ValidationError

#: Les champs que le §9.2 nomme, ligne par ligne, et la piece qui les porte.
#: Ecrire le chemin exact plutot que « un champ de marge quelque part » :
#: un renommage qui ferait disparaitre le champ doit faire rougir CE test,
#: pas passer inapercu.
CHAMPS_NOMMES_PAR_LE_CDC: list[tuple[str, str]] = [
    # « Champs internes — marge, cout de revient, commentaires de gestion —
    # exclus par defaut de toute correspondance. »
    ("sales.SalesOrder", "lines[].margin_pct"),
    ("sales.SalesOrder", "lines[].cost_estimate_mga"),
    ("sales.SalesOrder", "internal_notes"),
    ("sales.SalesQuotation", "lines[].margin_pct"),
    ("sales.SalesQuotation", "lines[].cost_estimate_mga"),
    ("sales.SalesQuotation", "internal_notes"),
    # « Aucun numero de compte complet dans une trace ou une charge utile
    # archivee. »
    ("accounting.AccMove", "lines[].account_code"),
    ("accounting.AccMove", "bank_account_number"),
]


@pytest.mark.parametrize(("document_code", "path"), CHAMPS_NOMMES_PAR_LE_CDC)
def test_the_fields_the_specification_names_are_declared_and_refused(
    document_code: str, path: str
) -> None:
    """Chacun des champs nommes par le §9.2 est declare INTERDIT.

    Declare, pas omis : un champ omis est deja refuse par la fermeture,
    mais rien ne casse le jour ou quelqu'un l'ajoute aux champs emis. Un
    champ nomme interdit, si — et c'est ce test qui casse."""
    document = get_outbound_document(document_code)
    assert document is not None, f"{document_code} n'est pas declare liable"
    champ = document.get_field(path)
    assert champ is not None, (
        f"{document_code} ne declare plus « {path} ». Le §9.2 le NOMME : "
        "il doit rester declare, et interdit."
    )
    assert champ.is_forbidden, f"« {path} » n'est plus interdit de sortie sur {document_code}"
    assert path not in document.emitted_paths

    with pytest.raises(SourceFieldRefusedError):
        validate_source_path(document_code, path)


def test_the_crm_lead_declares_which_operation_needs_each_personal_field() -> None:
    """§9.2 : « minimisation obligatoire — seuls les champs exiges par
    l'operation partent ».

    La minimisation ne se verifie pas en lisant une liste blanche : elle
    exige que chaque champ personnel dise QUELLE operation l'exige. Ce test
    verifie que le telephone du client n'est pas exige par toutes les
    operations — sans quoi « minimisation » ne serait qu'un mot, et la
    liaison e-facture emporterait le numero parce qu'il etait dans la
    fiche."""
    piste = get_outbound_document("crm.CrmLead")
    assert piste is not None
    telephone = piste.get_field("phone")
    assert telephone is not None
    assert telephone.required_by != OPERATION_CODES, (
        "Le telephone est declare exige par les huit operations : la "
        "minimisation du §9.2 n'a plus aucun effet."
    )

    # Soumettre a un dispositif fiscal (OP4) n'a aucun besoin du telephone.
    with pytest.raises(SourceFieldRefusedError):
        validate_source_path("crm.CrmLead", "phone", operations=["OP4"])
    # Initier un mouvement d'argent (OP5), si.
    validate_source_path("crm.CrmLead", "phone", operations=["OP5"])


def test_no_payroll_document_can_ever_be_declared_liable() -> None:
    """§9.2, ligne « Remuneration et donnees de paie » : « Interdiction
    absolue. Aucune liaison ne peut avoir pour source un objet du domaine
    Paie [...] Verifie en integration continue. »

    L'exception que le cahier menage — l'ordre de virement — n'en est pas
    une ici : quand il sera livre (bloc E, BNK-4) il sera un document
    d'`accounting`, pas de `payroll`. L'interdit reste donc absolu sur ce
    prefixe, et se lit d'un coup d'oeil."""
    fautifs = [
        document.code
        for document in list_outbound_documents()
        if document.code.split(".")[0] in {"payroll", "hr"}
    ]
    assert not fautifs, (
        f"Documents du domaine Paie declares liables : {fautifs}. Le §9.2 l'interdit absolument."
    )


def test_pruning_removes_a_forbidden_field_even_when_the_builder_emits_it() -> None:
    """La seconde barriere, et la seule qui protege contre l'inattention.

    Le module declare ce qui peut sortir ET construit la projection. Si
    seule la declaration protegeait, un `builder` distrait suffirait a tout
    defaire. `project_document` elague — et c'est verifie ici en donnant au
    registre un `builder` qui emet DELIBEREMENT la marge."""
    from apps.core.services.outbound_schemas import _DOCUMENTS, register_outbound_document

    code = "tests.DocumentBavard"

    def builder_bavard(_object_id: object) -> dict[str, object]:
        return {
            "reference": "D-1",
            "internal_notes": "ne pas envoyer",
            "lines": [{"description": "Cahier", "margin_pct": "42.00"}],
        }

    document = OutboundDocument(
        code=code,
        label="Document de test",
        category=CATEGORY_COMMERCIAL_DOCUMENT,
        fields=(
            OutboundField("reference", "Reference", CATEGORY_COMMERCIAL_DOCUMENT),
            OutboundField("lines[].description", "Designation", CATEGORY_COMMERCIAL_DOCUMENT),
            OutboundField(
                "lines[].margin_pct",
                "Marge",
                CATEGORY_COMMERCIAL_DOCUMENT,
                forbidden_because=(
                    "marge commerciale — champ interne au sens du §9.2, exclu par "
                    "defaut de toute correspondance"
                ),
            ),
            OutboundField(
                "internal_notes",
                "Notes internes",
                CATEGORY_COMMERCIAL_DOCUMENT,
                forbidden_because=(
                    "commentaire de gestion — champ interne au sens du §9.2, "
                    "redige pour des collegues et jamais pour le tiers"
                ),
            ),
        ),
        builder=builder_bavard,  # type: ignore[arg-type]
    )
    register_outbound_document(document)
    try:
        projection = project_document(code, "00000000-0000-0000-0000-000000000001")
    finally:
        _DOCUMENTS.pop(code, None)

    assert projection == {"reference": "D-1", "lines": [{"description": "Cahier"}]}


def test_a_forbidden_field_must_carry_a_written_motive() -> None:
    """Un interdit sans motif ecrit se leve par distraction.

    Meme discipline que `endpoint_governance` et `regulatory_governance` :
    le motif est long, parce que « interne » n'apprend rien a qui lit le
    refus."""
    for document in list_outbound_documents():
        for champ in document.fields:
            if champ.is_forbidden:
                assert len(champ.forbidden_because) >= MOTIF_MINIMUM, (
                    f"{document.code}.{champ.path} : motif d'interdiction trop court"
                )


def test_every_declared_field_belongs_to_a_category_that_may_leave() -> None:
    """Un champ EMIS ne peut pas relever d'une categorie que le §9.2 ferme.

    Les trois categories fermees — paie, production, preuve — n'ont aucun
    champ emis nulle part. Le verifier globalement plutot que par module :
    c'est la propriete qui compte, et elle doit tenir pour un module a
    venir comme pour les trois d'aujourd'hui."""
    for document in list_outbound_documents():
        for champ in document.fields:
            if champ.is_forbidden:
                continue
            assert CATEGORIES[champ.category].outbound_allowed, (
                f"{document.code}.{champ.path} est emis alors que sa categorie "
                f"« {champ.category} » est fermee par le §9.2"
            )


def test_the_registry_refuses_an_emitted_field_in_a_closed_category() -> None:
    """Auto-test du garde-fou : la fermeture est tenue par le registre, pas
    seulement par la discipline des declarants."""
    with pytest.raises(ValidationError):
        OutboundField("net_a_payer", "Net a payer", "paie")


def test_a_field_that_traverses_a_list_can_never_be_filterable() -> None:
    """Un filtre s'evalue sur une valeur unique.

    Sur un chemin de ligne (`lines[].qty`), la lecture rendrait `None` sans
    que rien ne le dise : le declencheur ne tirerait jamais, et le seul
    symptome serait une absence. Le registre le refuse a la declaration."""
    with pytest.raises(ValidationError):
        OutboundField("lines[].qty", "Quantite", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True)


def test_a_forbidden_field_can_never_be_filterable() -> None:
    """Filtrer sur un champ interdit choisit quels objets partent d'apres
    une donnee qui n'a pas le droit de sortir — donc la divulgue par
    deduction : le tiers apprend le signe de la marge en observant quelles
    commandes lui parviennent."""
    with pytest.raises(ValidationError):
        OutboundField(
            "margin_pct",
            "Marge",
            CATEGORY_COMMERCIAL_DOCUMENT,
            filterable=True,
            forbidden_because=(
                "marge commerciale — champ interne au sens du §9.2, exclu par "
                "defaut de toute correspondance"
            ),
        )
