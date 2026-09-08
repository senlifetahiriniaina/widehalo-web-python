"""T4 (bloc C) — la facture cesse d'être un document produit pour devenir
un document soumis.

**La phrase qui cadre le lot** (cahier, l.291) : « Le module Sales de la
Phase 1 n'est pas à réécrire, mais **son étape terminale change de
nature**. »

**Le mode d'attente EST le livrable** (P4-R1) : « le moteur de conformité
est réputé complet lorsqu'il produit, archive et met en file un document
normalisé **sans qu'aucune plateforme ne soit joignable** ». Ces tests
s'exécutent donc en très grande majorité SANS raccordement ouvert, ce qui
n'est pas une limitation du banc d'essai mais le scénario nominal du
premier client.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting.models import AccMove
from apps.accounting.services.einvoice_completeness import (
    RESOLVABLE_FIELD_CODES,
    is_submittable_type,
    submission_blockers,
)
from apps.accounting.services.einvoice_profile import (
    PROFILES,
    RESERVE_MINIMUM,
    get_profile,
)
from apps.accounting.services.einvoice_replay import open_fiscal_link
from apps.accounting.services.einvoice_submission import (
    CONNECTOR_CODE,
    DOCUMENT_TYPE,
    OUTCOME_INCOMPLETE,
    OUTCOME_NO_PROFILE,
    OUTCOME_NOT_CONCERNED,
    OUTCOME_QUEUED,
    OUTCOME_WAITING_FOR_LINK,
    submit_invoice,
)
from apps.accounting.services.einvoice_verdict import record_verdict, refresh_from_exchanges
from apps.accounting.tests.factories import AccMoveFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    """Une société COMPLÈTE au sens du profil : c'est le cas nominal, et
    partir d'une société incomplète ferait échouer tous les tests pour la
    même raison sans rapport avec ce qu'ils vérifient."""
    return Tenant.objects.create(
        code="T4-EFA",
        name="Émettrice SARL",
        nif="MG-NIF-500001",
        stat="MG-STAT-500001",
        address="Lot II M 12 Antananarivo",
        country_code="MG",
    )


def _facture(societe, *, partner_id=None, move_type=AccMove.TYPE_CUSTOMER_INVOICE):
    piece = AccMoveFactory(tenant=societe, move_type=move_type)
    piece.reference = "FAC-2026-0001"
    piece.partner_id = partner_id
    # ÉQUILIBRÉE : `acc_move_balanced_when_posted` refuse en base une pièce
    # publiée dont les deux totaux diffèrent, et une facture réelle
    # équilibre toujours. Ne renseigner que le crédit produisait un échec
    # qui ne disait rien du bloc C.
    piece.total_credit = Decimal("1200000.0000")
    piece.total_debit = Decimal("1200000.0000")
    piece.save(update_fields=["reference", "partner_id", "total_credit", "total_debit"])
    return piece


def _client_complet(societe):
    return create_partner(
        tenant=societe, name="Client SARL", roles=[], nif="MG-NIF-600001", stat="MG-STAT-600001"
    )


# --- Le profil pays (EFA-7) ------------------------------------------------


def test_every_profile_carries_a_written_reserve() -> None:
    """Un profil sans réserve écrite se lit comme une conformité vérifiée.

    Le dispositif malgache n'est pas ouvert : ni le cahier ni aucune source
    primaire accessible ne publie la liste des mentions. Le profil est donc
    une hypothèse assumée, et il doit le dire."""
    for code, profil in PROFILES.items():
        assert len(profil.reserve) >= RESERVE_MINIMUM, f"{code} : réserve trop courte"
        assert "DGI" in profil.reserve or "OECFM" in profil.reserve, (
            f"{code} : la réserve ne renvoie à aucune autorité compétente — elle "
            "ne dit donc pas auprès de qui la lever."
        )


def test_a_country_without_a_profile_submits_nothing(societe) -> None:
    """L'inconnu se dit, il ne se devine pas.

    Un tenant dans un pays sans profil ne soumet RIEN, plutôt que de
    soumettre selon les règles d'un autre pays — ce qui produirait un
    document que l'administration locale ne comprendrait pas, envoyé en
    son nom."""
    assert get_profile("ZZ") is None
    societe.country_code = "ZZ"
    societe.save(update_fields=["country_code"])

    with use_tenant(societe.id):
        rapport = submission_blockers(_facture(societe))

    assert rapport.no_profile is True
    assert rapport.can_submit is False


def test_every_required_field_can_actually_be_resolved() -> None:
    """Un profil ne peut pas exiger ce que rien ne sait renseigner.

    Le défaut que cette garde ferme est silencieux et permanent : un champ
    exigé mais absent du résolveur rendrait la facture ÉTERNELLEMENT
    incomplète, sur une mention qu'aucune saisie ne peut fournir. Le
    comptable corrigerait indéfiniment sans que rien ne bouge."""
    for code, profil in PROFILES.items():
        exiges = {champ.code for champ in profil.required_fields}
        orphelins = exiges - RESOLVABLE_FIELD_CODES
        assert not orphelins, (
            f"{code} : champs exigés que `_readable_values` ne sait pas résoudre "
            f"— {sorted(orphelins)}. La facture serait incomplète pour toujours."
        )


# --- Le refus qui nomme le champ (EFA-1) -----------------------------------


def test_a_missing_identifier_blocks_the_submission_and_names_the_field(societe) -> None:
    """« Un champ obligatoire manquant bloque la soumission et DÉSIGNE le
    champ, SANS invalider la facture » — mot pour mot le critère EFA-1.

    Les trois moitiés sont vérifiées ici : le rapport refuse, il nomme, et
    la facture ne bouge pas."""
    with use_tenant(societe.id):
        sans_nif = create_partner(tenant=societe, name="Client sans NIF", roles=[])
        piece = _facture(societe, partner_id=sans_nif.id)
        etat_avant = (piece.state, piece.invoice_state)

        rapport = submission_blockers(piece)

        assert rapport.can_submit is False
        codes = {champ.code for champ in rapport.missing}
        assert "customer_nif" in codes
        # DÉSIGNE : le libellé, pas le code technique.
        assert "NIF du client" in rapport.as_sentence()

        piece.refresh_from_db()
        assert (piece.state, piece.invoice_state) == etat_avant


def test_the_issuer_is_checked_as_much_as_the_customer(societe) -> None:
    """EFA-1 exige les mentions du vendeur autant que celles du client.

    C'est la raison pour laquelle le lot T3 a fait entrer `Tenant.nif` dans
    le même régime que `Partner.nif` : une facture soumise sans
    l'identifiant de celui qui l'émet est refusée de la même façon."""
    societe.nif = ""
    societe.stat = ""
    societe.save(update_fields=["nif", "stat"])

    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        rapport = submission_blockers(piece)

    codes = {champ.code for champ in rapport.missing}
    assert {"issuer_nif", "issuer_stat"} <= codes


def test_a_complete_invoice_has_nothing_missing(societe) -> None:
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        rapport = submission_blockers(piece)

    assert rapport.missing == ()
    assert rapport.can_submit is True


def test_an_ordinary_entry_is_never_submitted(societe) -> None:
    """Une écriture diverse n'a jamais eu vocation à partir.

    « Hors du champ » et « en attente de soumission » sont deux réponses
    opposées : les confondre ferait apparaître toute la comptabilité dans
    la file d'attente fiscale, et noierait les quelques pièces qui doivent
    vraiment y être."""
    with use_tenant(societe.id):
        ecriture = _facture(societe, move_type=AccMove.TYPE_ENTRY)
        assert is_submittable_type(ecriture) is False
        assert submit_invoice(ecriture).outcome == OUTCOME_NOT_CONCERNED


def test_a_supplier_invoice_is_not_ours_to_submit(societe) -> None:
    """C'est son ÉMETTEUR qui la soumet. La soumettre à notre tour créerait
    un doublon chez l'administration, au nom de quelqu'un d'autre."""
    with use_tenant(societe.id):
        piece = _facture(societe, move_type=AccMove.TYPE_SUPPLIER_INVOICE)
        assert submit_invoice(piece).outcome == OUTCOME_NOT_CONCERNED


# --- Le mode d'attente EST le livrable (EFA-2) -----------------------------


def test_without_any_link_the_document_is_still_produced_and_archived(societe) -> None:
    """« En l'absence de raccordement ouvert, le document est produit,
    signé, archivé et mis en file ; AUCUNE ERREUR n'est présentée à
    l'utilisateur » — EFA-2.

    Ce test est le scénario nominal du premier client, pas un cas
    dégradé : le cahier répute le moteur COMPLET lorsqu'il fait cela sans
    qu'aucune plateforme ne soit joignable (P4-R1)."""
    from apps.core.models.document import Document

    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        resultat = submit_invoice(piece)

        assert resultat.outcome == OUTCOME_WAITING_FOR_LINK
        assert resultat.is_blocked is False, "une attente n'est pas un blocage"
        assert resultat.archived is True
        assert Document.objects.filter(tenant=societe).count() == 1

        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_TO_SUBMIT


def test_an_incomplete_invoice_writes_nothing_at_all(societe) -> None:
    """Le refus d'EFA-1 ne laisse aucune trace sur la pièce.

    Inscrire un `fiscal_state` ici dirait un état que la facture peut
    quitter par une simple correction de la fiche du tiers — donc un état
    faux dès que quelqu'un corrige, et que rien ne remettrait à jour."""
    from apps.core.models.document import Document

    with use_tenant(societe.id):
        sans_nif = create_partner(tenant=societe, name="Incomplet", roles=[])
        piece = _facture(societe, partner_id=sans_nif.id)

        resultat = submit_invoice(piece)

        assert resultat.outcome == OUTCOME_INCOMPLETE
        assert resultat.is_blocked is True
        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_NOT_CONCERNED
        assert Document.objects.filter(tenant=societe).count() == 0


def test_a_country_without_profile_is_not_presented_as_a_failure(societe) -> None:
    societe.country_code = "ZZ"
    societe.save(update_fields=["country_code"])
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        assert submit_invoice(piece).outcome == OUTCOME_NO_PROFILE


def test_the_submitted_document_never_carries_a_full_account_number(societe) -> None:
    """§9.2 : « aucun numéro de compte complet dans une trace ou une charge
    utile archivée ».

    Le document est construit depuis la projection déclarée du lot T0, qui
    n'émet que la CLASSE du compte. Le reconstruire à la main ici aurait
    contourné cette déclaration sans qu'aucune garde ne s'en aperçoive —
    c'est exactement le défaut que T0 existait pour fermer."""
    from apps.accounting.services.einvoice_submission import build_structured_document

    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        document = build_structured_document(piece)

    lignes = document["piece"].get("lines", [])
    for ligne in lignes:
        assert "account_code" not in ligne
    assert document["emetteur"]["nif"] == "MG-NIF-500001"
    assert document["client"]["nif"] == "MG-NIF-600001"


def test_the_signed_bytes_are_stable_across_two_renderings(societe) -> None:
    """La signature porte sur des octets : deux rendus du même document
    doivent être identiques, sinon une vérification faite plus tard échoue
    sans que rien ne dise pourquoi.

    Le défaut qui a rendu ce test nécessaire n'était pas théorique :
    `json.dumps` sans convertisseur explosait sur toute facture réelle
    (dates, décimaux), et le corriger par un `default=str` aurait fait
    dépendre le format soumis à une administration du `__str__` d'un type
    Python."""
    from apps.accounting.services.einvoice_submission import (
        build_structured_document,
        canonical_bytes,
    )

    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        document = build_structured_document(piece)
        assert canonical_bytes(document) == canonical_bytes(document)
        # Les décimaux ne partent jamais en notation exponentielle, et les
        # dates sont en ISO 8601 — pas au format d'affichage local.
        rendu = canonical_bytes(document).decode("utf-8")
        assert "E+" not in rendu and "e+" not in rendu
        assert piece.date.isoformat() in rendu


def test_an_unrenderable_type_raises_instead_of_leaking_a_repr() -> None:
    """Un type inattendu LÈVE plutôt que de partir sous son `repr`.

    Un objet rendu `<AccAccount: 411100>` serait à la fois illisible pour
    l'administration et une fuite : le §9.2 interdit précisément le numéro
    de compte complet dans une charge utile archivée."""
    from apps.accounting.services.einvoice_submission import canonical_bytes

    class Inattendu:
        def __str__(self) -> str:  # pragma: no cover - jamais appelé
            return "411100"

    with pytest.raises(TypeError, match="non sérialisable"):
        canonical_bytes({"x": Inattendu()})


# --- Le certificat de signature (EFA-8) ------------------------------------


def _cle_privee_pem() -> str:
    """Une clé RSA jetable, générée pour ce test.

    Générée et non figée dans le dépôt : une clé privée en clair dans un
    fichier versionné est une clé compromise, même « de test » — le jour
    où quelqu'un la recopie dans une configuration réelle, elle est
    publique depuis le premier commit."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return cle.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _certificat(societe, *, expire_dans_jours: int | None):
    """Pose un certificat sur la liaison fiscale de cette société."""
    from apps.flows.models import FlwCredential

    liaison = _liaison_fiscale(societe, active=True)
    echeance = (
        None if expire_dans_jours is None else timezone.now() + dt.timedelta(days=expire_dans_jours)
    )
    FlwCredential.objects.create(
        tenant=societe,
        connector=liaison.connector,
        label="Certificat fiscal",
        kind=FlwCredential.KIND_CERTIFICATE,
        secret=_cle_privee_pem(),
        secret_hint="se termine par 4f2a",
        expires_at=echeance,
    )
    return liaison


def test_a_valid_certificate_signs_the_submission(societe) -> None:
    """EFA-2 : le document est « produit, SIGNÉ, archivé et mis en file »."""
    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=365)
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        resultat = submit_invoice(piece)

        assert resultat.signed is True
        assert resultat.outcome == OUTCOME_QUEUED


def test_an_expired_certificate_refuses_the_submission_before_it_leaves(societe) -> None:
    """« Une signature avec certificat expiré est REFUSÉE AVANT
    SOUMISSION » — EFA-8, mot pour mot.

    « Avant » n'est pas un détail de formulation : le refus doit tomber
    avant l'archivage et avant la mise en file, sans quoi l'administration
    recevrait une soumission qu'elle rejettera après l'avoir enregistrée,
    et le dépôt garderait l'archive d'un document qui n'aurait jamais dû
    partir."""
    from apps.core.models.document import Document
    from apps.flows.models import FlwExchange

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=-1)
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        with pytest.raises(ValidationError, match="expiré"):
            submit_invoice(piece)

        assert Document.objects.filter(tenant=societe).count() == 0, (
            "le document a été archivé alors que la signature était refusée"
        )
        assert not FlwExchange.objects.filter(tenant=societe).exists(), (
            "la soumission est partie malgré un certificat expiré"
        )


def test_no_certificate_at_all_is_not_an_error(societe) -> None:
    """Ne pas avoir encore fourni son certificat est l'état normal de toute
    installation qui n'a pas ouvert de raccordement.

    EFA-2 interdit d'y présenter une erreur : le document est produit et
    archivé, simplement pas signé. La différence avec le certificat expiré
    est celle entre « pas encore équipé », qui n'appelle aucune action, et
    « équipé d'un moyen sans valeur », qui en appelle une tout de suite."""
    with use_tenant(societe.id):
        _liaison_fiscale(societe, active=True)
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        resultat = submit_invoice(piece)

        assert resultat.signed is False
        assert resultat.outcome == OUTCOME_QUEUED
        assert resultat.archived is True


def test_an_expiry_within_thirty_days_raises_an_alert(societe) -> None:
    """« L'expiration prochaine déclenche une alerte AU MOINS trente jours
    avant échéance » — le critère pose un plancher, pas une cible."""
    from apps.flows.services.public import describe_signing_certificate

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=20)
        etat = describe_signing_certificate(societe, connector_code=CONNECTOR_CODE)

    assert etat["present"] is True
    assert etat["expiring_soon"] is True
    assert etat["expired"] is False
    assert etat["days_remaining"] <= 30


def test_a_certificate_valid_for_a_year_raises_no_alert(societe) -> None:
    """Alerter trop tôt vide l'alerte de son sens : un exploitant qui voit
    « expire bientôt » toute l'année cesse de le lire."""
    from apps.flows.services.public import describe_signing_certificate

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=200)
        etat = describe_signing_certificate(societe, connector_code=CONNECTOR_CODE)

    assert etat["expiring_soon"] is False


def test_an_already_expired_certificate_does_not_expire_soon(societe) -> None:
    """« Expire bientôt » et « a expiré » sont deux messages, deux urgences
    et deux écrans. Les confondre ferait afficher « expire dans -3 jours »,
    ce qui ne veut rien dire et fait douter de tout le reste."""
    from apps.flows.services.public import describe_signing_certificate

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=-3)
        etat = describe_signing_certificate(societe, connector_code=CONNECTOR_CODE)

    assert etat["expired"] is True
    assert etat["expiring_soon"] is False


def test_a_certificate_without_a_deadline_is_never_refused(societe) -> None:
    """Un certificat sans échéance connue n'est pas réputé éternel : il est
    réputé NON SURVEILLÉ.

    Le refuser bloquerait une soumission sur une donnée que l'exploitant a
    seulement omis de saisir — une omission de paramétrage ne doit pas
    avoir la même conséquence qu'un certificat périmé."""
    from apps.flows.services.public import describe_signing_certificate

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=None)
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        assert submit_invoice(piece).signed is True
        etat = describe_signing_certificate(societe, connector_code=CONNECTOR_CODE)
        assert etat["expiring_soon"] is False
        assert etat["days_remaining"] is None


def test_the_private_key_never_crosses_the_module_boundary(societe) -> None:
    """La surface publique rend la SIGNATURE, jamais le MOYEN.

    Le cahier est catégorique sur le logement d'un secret (§13.2 : « table
    à part, chiffrée, jamais exportée »). Si `accounting` devait signer
    lui-même, il faudrait lui rendre la clé — c'est-à-dire faire traverser
    un secret à une frontière de module pour qu'il soit utilisé ailleurs.
    Ce test vérifie qu'aucune matière secrète ne figure dans ce que la
    surface publique renvoie."""
    from apps.flows.services.public import describe_signing_certificate, sign_document

    with use_tenant(societe.id):
        _certificat(societe, expire_dans_jours=365)
        etat = describe_signing_certificate(societe, connector_code=CONNECTOR_CODE)
        signature = sign_document(societe, connector_code=CONNECTOR_CODE, payload=b"x")

    assert "PRIVATE KEY" not in repr(etat)
    assert "PRIVATE KEY" not in repr(signature)
    assert set(etat) == {
        "present",
        "label",
        "hint",
        "expires_at",
        "expired",
        "expiring_soon",
        "days_remaining",
    }
    assert signature is not None
    assert set(signature) == {"algorithm", "value", "certificate_hint", "signed_at"}


# --- Les trois axes sont orthogonaux (EFA-6) -------------------------------


def test_a_posted_invoice_still_accepts_a_fiscal_verdict(societe) -> None:
    """EFA-6, et le point qu'il ne fallait pas SUPPOSER.

    Le trigger d'immuabilité (migration 0005) énumère les colonnes
    COMPTABLES qu'une pièce publiée ne peut plus voir bouger — c'est une
    liste négative, donc `fiscal_state` y est autorisé par construction.
    « Par construction » est exactement le genre d'hypothèse qui se révèle
    fausse en production : ce test la vérifie contre la vraie base, trigger
    armé."""
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        piece.state = AccMove.STATE_POSTED
        piece.save(update_fields=["state"])

        record_verdict(
            piece,
            exchange_state="accepte",
            raw='{"code":"OK","id":"FISC-2026-77"}',
            fiscal_reference="FISC-2026-77",
            marking="QR:abc123",
        )

        piece.refresh_from_db()
        assert piece.state == AccMove.STATE_POSTED
        assert piece.fiscal_state == AccMove.FISCAL_STATE_ACCEPTED


def test_a_verdict_does_not_move_the_settlement_and_vice_versa(societe) -> None:
    """« Une facture peut être encaissée AVANT d'avoir obtenu son verdict,
    et un verdict peut arriver APRÈS l'encaissement, sans incohérence de
    statut ni blocage comptable » — EFA-6.

    Le cahier nomme ce piège en premier (l.431) : « le modèle ne doit donc
    pas les séquencer ». C'est pourquoi l'état fiscal est un TROISIÈME axe
    et non une valeur de plus dans `invoice_state`, qui mêle déjà
    validation et règlement."""
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        piece.invoice_state = AccMove.INVOICE_STATE_PAID
        piece.fiscal_state = AccMove.FISCAL_STATE_AWAITING
        piece.save(update_fields=["invoice_state", "fiscal_state"])

        # Le verdict arrive APRÈS l'encaissement.
        record_verdict(piece, exchange_state="accepte", raw="{}", fiscal_reference="F-1")

        piece.refresh_from_db()
        assert piece.invoice_state == AccMove.INVOICE_STATE_PAID, (
            "le verdict fiscal a déplacé le règlement — les axes sont séquencés"
        )
        assert piece.fiscal_state == AccMove.FISCAL_STATE_ACCEPTED


# --- Le verdict, dans sa forme d'origine (EFA-4) ---------------------------


def test_the_raw_verdict_is_kept_beside_its_interpretation(societe) -> None:
    """« Le verdict reçu est conservé DANS SA FORME D'ORIGINE, en plus de
    son interprétation » — EFA-4.

    Une interprétation est révisable : le jour où l'on découvre qu'un code
    de rejet signifiait autre chose, on relit les verdicts bruts et on
    corrige la lecture. N'avoir gardé que l'interprétation ne laisserait
    rien à relire."""
    brut = '{"statut":"REJETE","motif":"NIF client inconnu","ref":"X-9"}'
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        record_verdict(piece, exchange_state="rejete", raw=brut, fiscal_reference="X-9")

        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_REJECTED
        assert piece.fiscal_verdict_raw == brut, "la forme d'origine a été reformatée"
        assert piece.fiscal_settled_at is not None


def test_an_undecided_exchange_never_overwrites_a_verdict_already_received(societe) -> None:
    """Un échange qui n'a pas tranché ne dit rien du sort fiscal.

    Sur un canal asynchrone, deux messages arrivent dans le désordre : si
    « en file » écrasait « accepté », un accusé de réception tardif
    effacerait le verdict. C'est le pendant de la leçon de T3 sur les
    verdicts reconduits."""
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        record_verdict(piece, exchange_state="accepte", raw="{}", fiscal_reference="F-2")

        record_verdict(piece, exchange_state="en_file", raw="ignore", fiscal_reference="")

        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_ACCEPTED
        assert piece.fiscal_reference == "F-2"


def test_refreshing_without_any_exchange_changes_nothing(societe) -> None:
    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        refresh_from_exchanges(piece)
        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_NOT_CONCERNED


# --- La reprise à l'ouverture (EFA-3) --------------------------------------


def _liaison_fiscale(societe, *, active: bool):
    """Une liaison vers le connecteur fiscal, construite SOUS la société
    active — `FlwLink` hérite de la RLS."""
    from apps.flows.models import FlwLink
    from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

    connecteur = FlwConnectorFactory(tenant=societe, code=CONNECTOR_CODE)
    return FlwLinkFactory(
        tenant=societe,
        connector=connecteur,
        state=FlwLink.STATE_ACTIVE if active else FlwLink.STATE_DRAFT,
    )


def test_opening_the_link_replays_what_was_waiting_in_chronological_order(societe) -> None:
    """« L'ouverture d'un raccordement provoque le rejeu de la file en
    attente dans l'ordre chronologique, sans perte, sans doublon et sans
    intervention manuelle autre que la confirmation initiale » — EFA-3.

    L'ordre est celui de la DATE DE PIÈCE, pas de la saisie : deux factures
    tapées le même après-midi pour des dates différentes partent dans
    l'ordre où elles ont été émises. C'est ce que « chronologique » veut
    dire pour une administration."""
    from apps.flows.models import FlwExchange

    with use_tenant(societe.id):
        client = _client_complet(societe)
        # Saisies dans le DÉSORDRE : la plus récente d'abord.
        tardive = _facture(societe, partner_id=client.id)
        tardive.reference = "FAC-2026-0002"
        tardive.date = dt.date(2026, 3, 20)
        tardive.save(update_fields=["reference", "date"])

        precoce = _facture(societe, partner_id=client.id)
        precoce.reference = "FAC-2026-0003"
        precoce.date = dt.date(2026, 1, 5)
        precoce.save(update_fields=["reference", "date"])

        # Aucune liaison : les deux sont produites et mises en attente.
        assert submit_invoice(tardive).outcome == OUTCOME_WAITING_FOR_LINK
        assert submit_invoice(precoce).outcome == OUTCOME_WAITING_FOR_LINK

        _liaison_fiscale(societe, active=False)
        rapport = open_fiscal_link(societe)

        assert rapport.considered == 2
        assert rapport.queued == 2
        assert rapport.still_pending == 0

        echanges = list(
            FlwExchange.objects.filter(tenant=societe, document_type=DOCUMENT_TYPE).order_by(
                "created_at"
            )
        )
        assert [str(e.document_id) for e in echanges] == [str(precoce.id), str(tardive.id)], (
            "la file a été rejouée dans l'ordre de saisie, pas dans l'ordre des pièces"
        )


def test_replaying_twice_creates_no_duplicate(societe) -> None:
    """« Sans doublon » — et il est tenu à deux étages.

    Une pièce déjà partie n'est plus en attente, donc elle n'entre pas dans
    la file : le rejeu ne refait pas le travail. Et si deux rejeux se
    chevauchaient malgré tout, la clef d'idempotence du hub refuserait le
    second en base. Ce test vérifie le premier étage ; le second est tenu
    par une contrainte `UNIQUE`."""
    from apps.flows.models import FlwExchange

    with use_tenant(societe.id):
        piece = _facture(societe, partner_id=_client_complet(societe).id)
        submit_invoice(piece)
        _liaison_fiscale(societe, active=False)

        premier = open_fiscal_link(societe)
        second = open_fiscal_link(societe)

        assert premier.queued == 1
        assert second.considered == 0, "une pièce déjà partie est revenue dans la file"
        assert FlwExchange.objects.filter(tenant=societe, document_type=DOCUMENT_TYPE).count() == 1


def test_an_invoice_that_still_cannot_go_stays_in_the_queue(societe) -> None:
    """« Sans perte » vaut aussi pour ce qui échoue encore.

    Une pièce dont une mention a disparu entre la mise en attente et
    l'ouverture — quelqu'un a vidé la fiche du tiers — reste dans la file
    au lieu d'être écartée. L'écarter la ferait disparaître sans que
    personne ne l'apprenne."""
    with use_tenant(societe.id):
        client = _client_complet(societe)
        piece = _facture(societe, partner_id=client.id)
        submit_invoice(piece)

        client.nif = ""
        client.save(update_fields=["nif"])

        _liaison_fiscale(societe, active=False)
        rapport = open_fiscal_link(societe)

        assert rapport.considered == 1
        assert rapport.queued == 0
        assert rapport.still_pending == 1
        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_TO_SUBMIT


def test_with_an_open_link_the_invoice_is_queued_and_awaits_a_verdict(societe) -> None:
    """Le chemin nominal, une fois le raccordement ouvert."""
    from apps.flows.models import FlwExchange

    with use_tenant(societe.id):
        _liaison_fiscale(societe, active=True)
        piece = _facture(societe, partner_id=_client_complet(societe).id)

        resultat = submit_invoice(piece)

        assert resultat.outcome == OUTCOME_QUEUED
        assert resultat.exchange_id is not None
        piece.refresh_from_db()
        assert piece.fiscal_state == AccMove.FISCAL_STATE_AWAITING

        echange = FlwExchange.objects.get(id=resultat.exchange_id)
        assert echange.payload.retain_until is not None, (
            "la durée d'archivage du profil pays n'a pas été portée sur la "
            "charge utile — la purge appliquerait sa politique par défaut à "
            "une soumission fiscale"
        )
