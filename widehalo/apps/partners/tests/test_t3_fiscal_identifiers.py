"""T3 — l'identifiant fiscal cesse d'être une chaîne libre.

**Le critère** (Phase 4, l.224) : « la qualité du référentiel tiers devient
bloquante : un identifiant fiscal absent ou faux, qui n'empêchait qu'une
impression jusqu'ici, empêchera désormais une validation ».

**Où le refus tombe, et pourquoi ce n'est pas là où la prose le dit.** Deux
passages du cahier divergent. La prose ci-dessus parle de « validation », et
elle figure dans un paragraphe intitulé « Trois travaux que la Phase 4
impose au CLIENT, et qui ne sont pas du développement ». Le critère EFA-1,
lui, est précis : « un champ obligatoire manquant **bloque la soumission**
et désigne le champ, **sans invalider la facture** ». La règle de cette
vague tranche — le critère prévaut. T3 livre donc le format, la
normalisation, la vérification et la mesure ; c'est le contrôle de
complétude du bloc C qui refusera la soumission.

Conséquence, et elle est bonne : ce lot ne casse la facturation de personne
du jour au lendemain. Le client a le temps de nettoyer son référentiel — et
`audit_fiscal_identifiers` lui dit exactement ce qu'il y a à nettoyer.

**Ce que ce module NE prétend pas faire.** Le format exact du NIF malgache
n'est publié dans aucune source primaire accessible à ce dépôt ; le jeu de
démonstration lui-même emploie des valeurs fictives (« MG-NIF-100001 »).
Écrire une expression régulière stricte fabriquerait une règle fiscale et
la présenterait comme vérifiée. Le contrôle est donc STRUCTUREL — longueur
et caractères admis — et sa réserve est écrite dans le registre. C'est la
même posture qu'au lot T2 pour `tva.taux_export`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.fiscal_identifiers import (
    FORMATS,
    IDENTIFIER_NIF,
    RESERVE_MINIMUM,
    canonical,
    normalize,
    validate_identifier,
)
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    return Tenant.objects.create(code="T3-PART", name="Référentiel SARL")


# --- Le registre lui-même -------------------------------------------------


def test_every_declared_format_carries_a_written_reserve() -> None:
    """Un contrôle réglementaire sans réserve écrite se lit comme une
    conformité vérifiée. Le registre l'exige à la déclaration ; ce test
    vérifie que les formats RÉELLEMENT chargés la portent."""
    for format_declare in FORMATS.values():
        assert len(format_declare.reserve) >= RESERVE_MINIMUM
        assert "OECFM" in format_declare.reserve or "DGI" in format_declare.reserve


def test_a_country_without_a_declared_format_controls_nothing() -> None:
    """L'inconnu se dit, il ne se devine pas.

    Inventer un motif pour un pays qu'on ne connaît pas serait pire que de
    ne rien contrôler : le refus porterait sur une règle fabriquée."""
    assert validate_identifier("n'importe quoi", identifier=IDENTIFIER_NIF, country_code="FR") == (
        "N'IMPORTE QUOI"
    )


# --- Normalisation et rapprochement ---------------------------------------


def test_normalisation_keeps_the_separators_the_accountant_typed() -> None:
    """Réécrire la saisie d'un comptable au motif qu'on croit savoir mieux
    est un service qu'on ne rend qu'une fois : l'une des deux formes en
    présence peut être la forme officielle."""
    assert normalize("  mg-nif-100002  ") == "MG-NIF-100002"
    assert normalize("mg  nif   100002") == "MG NIF 100002"


def test_the_canonical_form_is_what_matches_two_spellings() -> None:
    assert canonical("MG-NIF-100002") == canonical("mg nif 100002") == "MGNIF100002"


# --- Le refus à l'enregistrement ------------------------------------------


@pytest.mark.parametrize("valeur", ["n/a", "-", "??", "x"])
def test_a_structurally_impossible_identifier_is_refused(societe, valeur: str) -> None:
    """Ce que le contrôle structurel attrape réellement : le déchet. Pas un
    NIF authentique — on ne sait pas le reconnaître — mais tout ce qui ne
    peut pas en être un."""
    with use_tenant(societe.id), pytest.raises(ValidationError):
        Partner.objects.create(tenant=societe, reference="P-KO", name="Tiers", nif=valeur)


def test_an_identifier_carrying_free_text_is_refused(societe) -> None:
    """Le cas réel : quelqu'un saisit une note dans le champ NIF."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        Partner.objects.create(
            tenant=societe,
            reference="P-TEXTE",
            name="Tiers",
            nif="à demander au client, il n'a pas répondu",
        )
    assert "NIF" in " ".join(refus.value.messages)


def test_a_valid_identifier_is_stored_normalised(societe) -> None:
    """Le témoin. Sans lui, refuser TOUT donnerait le même vert que refuser
    ce qu'il faut."""
    with use_tenant(societe.id):
        partenaire = Partner.objects.create(
            tenant=societe, reference="P-OK", name="Tiers", nif="  mg-nif-100001 "
        )
        partenaire.refresh_from_db()
    assert partenaire.nif == "MG-NIF-100001"


def test_an_empty_identifier_is_accepted(societe) -> None:
    """EFA-1 refuse l'absence à la SOUMISSION, pas à la saisie. Exiger le
    champ à la création rendrait le CRM inutilisable : un prospect saisi en
    trente secondes n'a pas encore de NIF."""
    with use_tenant(societe.id):
        partenaire = Partner.objects.create(tenant=societe, reference="P-VIDE", name="Prospect")
    assert partenaire.nif == ""


def test_the_refusal_holds_on_every_door_not_just_the_form(societe) -> None:
    """La garde vit dans `save()`, pas dans un formulaire : l'API, un
    import, une commande de reprise et un `shell` passent tous par là.
    Django ne fait tourner les validateurs de champ que dans
    `full_clean()`, jamais dans `save()` — c'est le défaut que ce montage
    ferme, et le même qu'au lot T1 pour `SalesTarget`."""
    with use_tenant(societe.id):
        with pytest.raises(ValidationError):
            create_partner(tenant=societe, name="Par le service", roles=[], nif="!!")
        with pytest.raises(ValidationError):
            Partner.objects.create(tenant=societe, reference="P-ORM", name="Par l'ORM", nif="!!")


def test_the_issuer_is_held_to_the_same_rule(societe) -> None:
    """EFA-1 exige les mentions du vendeur autant que celles du client :
    une facture soumise sans l'identifiant de celui qui l'émet est refusée
    de la même façon."""
    with pytest.raises(ValidationError):
        Tenant.objects.create(code="T3-EMET", name="Émetteur", nif="?")


# --- La détection de doublons, enfin utile --------------------------------


def test_two_spellings_of_the_same_identifier_now_raise_an_alert(societe) -> None:
    """**Le défaut fermé au passage.** Le rapprochement comparait des
    chaînes brutes : il ne voyait que les saisies rigoureusement
    identiques, c'est-à-dire le cas où l'utilisateur avait déjà fait
    attention. « MG-NIF-100002 » et « mg nif 100002 » désignaient le même
    tiers sans lever la moindre alerte."""
    with use_tenant(societe.id):
        create_partner(tenant=societe, name="Premier", roles=[], nif="MG-NIF-100002")
        create_partner(tenant=societe, name="Second", roles=[], nif="mg nif 100002")
        alertes = DuplicateAlert.objects.filter(tenant=societe)
    assert alertes.count() == 1


def test_two_genuinely_different_identifiers_raise_nothing(societe) -> None:
    """La contrepartie : sans elle, un rapprochement qui alerte toujours
    donnerait le même vert."""
    with use_tenant(societe.id):
        create_partner(tenant=societe, name="Premier", roles=[], nif="MG-NIF-100002")
        create_partner(tenant=societe, name="Second", roles=[], nif="MG-NIF-100003")
        assert not DuplicateAlert.objects.filter(tenant=societe).exists()


# --- La surface publique, pour qui devra soumettre ------------------------


def test_the_public_surface_reports_the_missing_identifier_by_name(societe) -> None:
    """EFA-1 : « désigne le champ ». Un appelant qui ne saurait que « c'est
    incomplet » ne pourrait pas le dire à l'utilisateur."""
    from apps.partners.services.public import (
        get_partner_fiscal_identity,
        missing_fiscal_identifiers,
    )

    with use_tenant(societe.id):
        sans = create_partner(tenant=societe, name="Sans NIF", roles=[])
        avec = create_partner(tenant=societe, name="Avec NIF", roles=[], nif="MG-NIF-100007")

        assert missing_fiscal_identifiers(sans.id) == ["nif"]
        assert missing_fiscal_identifiers(avec.id) == []
        assert missing_fiscal_identifiers(avec.id, required=("nif", "stat")) == ["stat"]

        identite = get_partner_fiscal_identity(avec.id)
        assert identite["nif"] == "MG-NIF-100007"
        assert identite["verification_state"] == Partner.VERIFICATION_NON_VERIFIE


def test_an_unknown_partner_answers_absence_rather_than_none(societe) -> None:
    """L'appelant qui teste « le NIF est-il présent ? » doit obtenir la
    bonne réponse — non — sans avoir à distinguer deux cas d'absence."""
    import uuid

    from apps.partners.services.public import get_partner_fiscal_identity

    with use_tenant(societe.id):
        identite = get_partner_fiscal_identity(uuid.uuid4())
    assert identite["nif"] == ""
    assert identite["partner_id"] is None


# --- La péremption de la vérification -------------------------------------


def test_a_confirmation_expires(societe) -> None:
    """Un tiers radié resterait « confirmé » pour toujours si personne ne
    faisait expirer la réponse. C'est ce qui distingue une mise en cache
    avec durée de validité (OP8) d'un horodatage d'archive."""
    from apps.partners.services.fiscal_verification import VALIDITY_DAYS, verification_is_stale

    with use_tenant(societe.id):
        partenaire = create_partner(
            tenant=societe, name="Vérifié jadis", roles=[], nif="MG-NIF-100008"
        )
        partenaire.fiscal_verification_state = Partner.VERIFICATION_CONFIRME
        partenaire.fiscal_verified_at = timezone.now() - dt.timedelta(days=VALIDITY_DAYS + 1)
        partenaire.save()

        assert verification_is_stale(partenaire)
        partenaire.fiscal_verified_at = timezone.now()
        assert not verification_is_stale(partenaire)


def test_a_never_verified_partner_is_not_stale(societe) -> None:
    """« Jamais vérifié » et « périmé » sont deux états différents. Les
    confondre ferait afficher « à revérifier » à toute une base qui n'a
    jamais été vérifiée."""
    from apps.partners.services.fiscal_verification import verification_is_stale

    with use_tenant(societe.id):
        partenaire = create_partner(tenant=societe, name="Jamais vu", roles=[], nif="MG-NIF-1009")
        assert not verification_is_stale(partenaire)


def test_verification_is_skipped_when_no_reference_link_exists(societe) -> None:
    """Ne pas avoir branché de référentiel est un état parfaitement normal,
    pas une erreur à signaler — et surtout pas un blocage. C'est la
    « dégradation en valeur saisie » du critère OP8."""
    from apps.partners.services.fiscal_verification import request_verification

    with use_tenant(societe.id):
        partenaire = create_partner(
            tenant=societe, name="Sans référentiel", roles=[], nif="MG-NIF-100010"
        )
        assert request_verification(partenaire) is None
        partenaire.refresh_from_db()
        assert partenaire.nif == "MG-NIF-100010"
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_NON_VERIFIE


def test_a_partner_without_any_identifier_is_never_sent_for_verification(societe) -> None:
    from apps.partners.services.fiscal_verification import request_verification

    with use_tenant(societe.id):
        partenaire = create_partner(tenant=societe, name="Rien à vérifier", roles=[])
        assert request_verification(partenaire) is None


def _referentiel_actif(societe):
    """Une liaison ACTIVE vers un référentiel fiscal, construite SOUS la
    société active.

    `FlwLink` hérite de `BaseModel`, donc de la RLS : une fixture qui la
    créerait hors `use_tenant` se verrait refuser l'insertion par la
    politique, avec un message (« new row violates row-level security
    policy ») qui ne désigne pas la cause."""
    from apps.flows.models import FlwLink
    from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory
    from apps.partners.services.fiscal_verification import CONNECTOR_CODE

    connecteur = FlwConnectorFactory(tenant=societe, code=CONNECTOR_CODE)
    return FlwLinkFactory(tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE)


def _echange_tranche(demande, *, verdict: str):
    """Fait suivre à l'échange le chemin réel de la machine à états jusqu'à
    son verdict — jamais une écriture directe de `state`.

    Écrire l'état à la main ferait passer ce test même le jour où la
    machine interdirait la transition, et le test dirait alors quelque
    chose de faux sur le produit."""
    from apps.flows.models import FlwExchange
    from apps.flows.services.exchange import transition_exchange

    echange = FlwExchange.objects.get(id=demande["id"])
    transition_exchange(echange, to_state=FlwExchange.STATE_SENT)
    return transition_exchange(echange, to_state=verdict, result_code="ref-01")


def test_a_confirmed_verdict_annotates_the_partner_without_rewriting_it(societe) -> None:
    """OP8 — « dégradation en valeur saisie ». Le référentiel ANNOTE : il
    ne réécrit jamais l'identifiant que le comptable a saisi.

    C'est la propriété la plus facile à perdre du lot : un service qui
    « corrige » un NIF sur la foi d'un tiers rend la saisie du comptable
    irrécupérable, et le cahier ne demande nulle part cette autorité."""
    from apps.flows.models import FlwExchange
    from apps.partners.services.fiscal_verification import (
        refresh_verification,
        request_verification,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(
            tenant=societe, name="Vérifiable", roles=[], nif="MG-NIF-100020"
        )
        demande = request_verification(partenaire)
        assert demande is not None

        _echange_tranche(demande, verdict=FlwExchange.STATE_ACCEPTED)
        refresh_verification(partenaire)

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_CONFIRME
        assert partenaire.fiscal_verified_at is not None
        assert partenaire.nif == "MG-NIF-100020"


def test_an_unknown_identifier_is_marked_but_never_erased(societe) -> None:
    """Le seul état qui CONTREDIT la saisie ne l'efface pas pour autant.

    Le cahier dit « dégradation en valeur saisie », pas « effacement sur
    désaccord » : un référentiel qui ne connaît pas encore un tiers
    fraîchement immatriculé ne doit pas vider sa fiche."""
    from apps.flows.models import FlwExchange
    from apps.partners.services.fiscal_verification import (
        refresh_verification,
        request_verification,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(
            tenant=societe, name="Introuvable", roles=[], nif="MG-NIF-100021"
        )
        demande = request_verification(partenaire)
        assert demande is not None

        _echange_tranche(demande, verdict=FlwExchange.STATE_REJECTED)
        refresh_verification(partenaire)

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_INTROUVABLE
        assert partenaire.nif == "MG-NIF-100021"


def test_an_exchange_still_in_flight_leaves_the_previous_verdict_alone(societe) -> None:
    """Une demande PARTIE n'est pas un verdict.

    Écraser une confirmation datée par « non vérifié » au moment où une
    nouvelle demande part ferait perdre l'information exactement quand on
    en a besoin — à la soumission, qui a lieu pendant que la demande est en
    vol."""
    from apps.partners.services.fiscal_verification import (
        refresh_verification,
        request_verification,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(tenant=societe, name="En vol", roles=[], nif="MG-NIF-100022")
        partenaire.fiscal_verification_state = Partner.VERIFICATION_CONFIRME
        partenaire.fiscal_verified_at = timezone.now()
        partenaire.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        assert request_verification(partenaire) is not None
        refresh_verification(partenaire)

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_CONFIRME


def test_an_unreachable_reference_concludes_nothing_about_the_identifier(societe) -> None:
    """FLX-2 — l'échec d'un tiers ne conclut rien sur la donnée.

    « Référentiel indisponible » et « introuvable au référentiel » sont deux
    lectures opposées pour le comptable : la première ne dit rien du tiers,
    la seconde le met en cause. Les confondre ferait suspecter des tiers
    parfaitement en règle chaque fois qu'un service tombe."""
    from apps.flows.models import FlwExchange
    from apps.partners.services.fiscal_verification import (
        refresh_verification,
        request_verification,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(
            tenant=societe, name="Référentiel muet", roles=[], nif="MG-NIF-100023"
        )
        demande = request_verification(partenaire)
        assert demande is not None

        _echange_tranche(demande, verdict=FlwExchange.STATE_FAILED)
        refresh_verification(partenaire)

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_INDISPONIBLE
        assert partenaire.nif == "MG-NIF-100023"


def test_an_expired_confirmation_is_re_dated_by_the_new_verdict(societe) -> None:
    """Une confirmation RECONDUITE re-date la fiche, même à verdict égal.

    Le trou que ce test ferme était silencieux, et c'est ce qui le rendait
    coûteux. `refresh_verification` ne réécrivait la fiche que si l'ÉTAT
    changeait ; une confirmation périmée revenant « confirmée » ne changeait
    donc rien, la fiche gardait sa vieille date, `partners_needing_
    verification` la voyait encore périmée — et la commande périodique en
    redemandait la vérification chaque nuit, indéfiniment, sans que la
    fiche ne bouge jamais. Le référentiel était interrogé pour rien et le
    comptable lisait une date fausse."""
    from apps.flows.models import FlwExchange
    from apps.partners.services.fiscal_verification import (
        VALIDITY_DAYS,
        refresh_verification,
        request_verification,
        verification_is_stale,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(
            tenant=societe, name="À revérifier", roles=[], nif="MG-NIF-9001"
        )
        vieille_date = timezone.now() - dt.timedelta(days=VALIDITY_DAYS + 30)
        partenaire.fiscal_verification_state = Partner.VERIFICATION_CONFIRME
        partenaire.fiscal_verified_at = vieille_date
        partenaire.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])
        assert verification_is_stale(partenaire) is True

        demande = request_verification(partenaire)
        assert demande is not None
        _echange_tranche(demande, verdict=FlwExchange.STATE_ACCEPTED)
        refresh_verification(partenaire)

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_CONFIRME
        assert partenaire.fiscal_verified_at > vieille_date
        assert verification_is_stale(partenaire) is False


def test_the_periodic_command_re_reads_an_expired_confirmation(societe) -> None:
    """La commande relit la MÊME file que celle qu'elle interroge.

    `_refresh_pending` ne regardait que les états « pas encore répondu » :
    une confirmation périmée n'y figurait pas, donc le verdict revenu pour
    elle n'était jamais lu. Demander et relire doivent porter sur le même
    ensemble, décalés d'une passe — sans quoi la commande demande sans
    fin ce qu'elle ne lit jamais."""
    from django.core.management import call_command

    from apps.flows.models import FlwExchange
    from apps.partners.services.fiscal_verification import (
        VALIDITY_DAYS,
        request_verification,
        verification_is_stale,
    )

    with use_tenant(societe.id):
        _referentiel_actif(societe)
        partenaire = create_partner(tenant=societe, name="Périmé", roles=[], nif="MG-NIF-9002")
        partenaire.fiscal_verification_state = Partner.VERIFICATION_CONFIRME
        partenaire.fiscal_verified_at = timezone.now() - dt.timedelta(days=VALIDITY_DAYS + 30)
        partenaire.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        demande = request_verification(partenaire)
        assert demande is not None
        _echange_tranche(demande, verdict=FlwExchange.STATE_ACCEPTED)

        call_command("verify_fiscal_identifiers", tenant_code=societe.code)

        partenaire.refresh_from_db()
        assert verification_is_stale(partenaire) is False


def test_correcting_the_identifier_forgets_the_verdict_it_no_longer_applies_to(societe) -> None:
    """Un verdict porte sur une VALEUR, pas sur une fiche.

    Le cas réel : un tiers est déclaré « introuvable au référentiel » parce
    que son NIF avait une coquille. Le comptable corrige. Sans cette
    remise à zéro, la fiche restait « introuvable » à sa vieille date pour
    toujours — la file de vérification ne reprend pas les verdicts (et
    c'est voulu), donc plus rien n'aurait jamais rouvert la question."""
    with use_tenant(societe.id):
        partenaire = create_partner(tenant=societe, name="Coquille", roles=[], nif="MG-NIF-9010")
        partenaire.fiscal_verification_state = Partner.VERIFICATION_INTROUVABLE
        partenaire.fiscal_verified_at = timezone.now()
        partenaire.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        partenaire.nif = "MG-NIF-9011"
        partenaire.save(update_fields=["nif"])

        partenaire.refresh_from_db()
        assert partenaire.nif == "MG-NIF-9011"
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_NON_VERIFIE
        assert partenaire.fiscal_verified_at is None


def test_a_save_that_leaves_the_identifier_alone_keeps_the_verdict(societe) -> None:
    """La remise à zéro ne se déclenche que sur l'identité fiscale.

    Renommer un tiers, changer son plafond de crédit ou lui ajouter un rôle
    n'apprend rien sur son NIF : perdre la confirmation à chaque
    modification de fiche rendrait la vérification inutilisable, et la
    commande périodique interrogerait le référentiel sans fin."""
    with use_tenant(societe.id):
        partenaire = create_partner(tenant=societe, name="Stable", roles=[], nif="MG-NIF-9012")
        date = timezone.now()
        partenaire.fiscal_verification_state = Partner.VERIFICATION_CONFIRME
        partenaire.fiscal_verified_at = date
        partenaire.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        partenaire.name = "Stable et renommé"
        partenaire.save()

        partenaire.refresh_from_db()
        assert partenaire.fiscal_verification_state == Partner.VERIFICATION_CONFIRME
        assert partenaire.fiscal_verified_at == date


def test_an_unavailable_reference_comes_back_into_the_queue(societe) -> None:
    """« Référentiel indisponible » veut dire que RIEN n'a été conclu.

    Le laisser hors de la file gèlerait définitivement un tiers sur une
    panne passagère du référentiel — l'inverse exact de ce que FLX-2
    demande, où l'échec d'un tiers ne décide jamais du sort d'une donnée
    métier."""
    from apps.partners.services.fiscal_verification import partners_needing_verification

    with use_tenant(societe.id):
        indisponible = create_partner(tenant=societe, name="Panne", roles=[], nif="MG-NIF-9013")
        indisponible.fiscal_verification_state = Partner.VERIFICATION_INDISPONIBLE
        indisponible.fiscal_verified_at = timezone.now()
        indisponible.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        introuvable = create_partner(tenant=societe, name="Verdict", roles=[], nif="MG-NIF-9014")
        introuvable.fiscal_verification_state = Partner.VERIFICATION_INTROUVABLE
        introuvable.fiscal_verified_at = timezone.now()
        introuvable.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])

        file_attente = {partner.id for partner in partners_needing_verification(societe)}

    assert indisponible.id in file_attente
    # Un verdict rendu ne se redemande pas chaque nuit : c'est la correction
    # de l'identifiant qui rouvre la question, testée juste au-dessus.
    assert introuvable.id not in file_attente


# --- La reprise qui chiffre -----------------------------------------------


def test_the_audit_command_counts_without_changing_anything(societe, capsys) -> None:
    """Un travail qu'on met à la charge de quelqu'un sans lui donner de quoi
    le mesurer n'est pas un travail : c'est une surprise.

    La commande LIT. Normaliser en masse réécrirait la saisie de comptables
    sans qu'ils l'aient demandée."""
    from django.core.management import call_command

    with use_tenant(societe.id):
        create_partner(tenant=societe, name="Sans NIF", roles=[])
        garde = create_partner(
            tenant=societe,
            name="Bien formé",
            roles=[],
            nif="MG-NIF-100011",
            credit_limit_mga=Decimal(0),
        )
        # Un identifiant devenu illégitime APRÈS coup : le format a pu se
        # resserrer, ou la donnée vient d'un import antérieur au contrôle.
        Partner.all_objects.filter(pk=garde.pk).update(nif="!!")

    call_command("audit_fiscal_identifiers", "--tenant-code", societe.code, "--details")
    sortie = capsys.readouterr().out

    assert "1 sans NIF" in sortie
    assert "mal formé" in sortie

    with use_tenant(societe.id):
        garde.refresh_from_db()
        assert garde.nif == "!!", "La commande a MODIFIÉ une donnée : elle ne doit que compter."
