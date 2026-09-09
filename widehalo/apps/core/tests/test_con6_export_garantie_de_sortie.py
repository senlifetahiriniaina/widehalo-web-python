"""T8 (bloc H, CON-6) — ce que l'archive de garantie de sortie contient, et
ce qu'elle n'emporte pas.

**Le critere** : « l'export de garantie de sortie produit l'integralite des
liaisons, echanges, verdicts et rapprochements dans un format documente et
relisible sans WideHalo. »

**Pourquoi ce fichier existe alors que la propriete etait deja vraie.**
`export_tenant_archive` parcourt `iter_concrete_basemodel_subclasses()` :
les quatre familles y etaient donc par construction, sans qu'on ait rien
ecrit pour cela. C'est exactement la situation de BNK-5 au lot T6 — une
propriete vraie PAR ACCIDENT, qu'aucun test ne tenait, et qui tombe le jour
ou quelqu'un restreint la boucle d'export a une liste de modeles « utiles ».

**« Relisible sans WideHalo » se prouve en ne se servant de rien d'autre.**
Ces tests ouvrent l'archive avec `zipfile` et `json` de la bibliotheque
standard, et lisent les valeurs comme le ferait le successeur du client. Un
test qui verifierait le contenu en reimportant l'archive prouverait
seulement que WideHalo se relit lui-meme — c'est-a-dire le contraire du
critere.

**La lecon d'instrument, payee ici.** La toute premiere version de la
mesure du secret cherchait le clair dans les OCTETS de l'archive :
`SECRET.encode() in archive_bytes`. Elle rendait `False` — et le secret
etait pourtant bien la, en clair, dans `data/flows.flwcredential.json`. Le
zip est COMPRESSE : le clair n'apparait nulle part tel quel dans ses
octets. L'instrument declarait le systeme sain. Toute verification porte
donc ici sur les entrees DECOMPRESSEES, jamais sur l'archive brute.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from decimal import Decimal

import pytest

from apps.accounting.models import AccBankStatementLine, AccMove
from apps.accounting.tests.factories import (
    AccBankStatementLineFactory,
    AccMoveFactory,
    AccMoveLineFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.services.tenant_export import export_tenant_archive
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwCredential, FlwExchange, FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.tests.factories import (
    FlwApiKeyFactory,
    FlwConnectorFactory,
    FlwCredentialFactory,
    FlwExchangeFactory,
    FlwLinkFactory,
    FlwPayloadFactory,
)

pytestmark = pytest.mark.django_db

#: Le clair est ecrit ici, dans le test, et cherche tel quel dans les
#: entrees decompressees. Une valeur improbable pour qu'une correspondance
#: fortuite soit exclue.
SECRET_DU_TIERS = "cle-api-du-tiers-que-l-archive-ne-doit-jamais-porter"

VERDICT_BRUT = '{"statut":"ACCEPTE","identifiant":"MG-2026-000123"}'
NUMERO_DE_LETTRAGE = "LET-T8-0001"


@pytest.fixture
def societe_avec_ses_flux() -> Tenant:
    """Une societe qui a reellement echange : une liaison, un echange, sa
    charge utile, un verdict fiscal sur une piece, et un rapprochement
    bancaire lettre.

    Les quatre familles que CON-6 nomme, plus l'identifiant de tiers qui ne
    doit pas suivre."""
    tenant = Tenant.objects.create(code="CON6", name="Garantie de sortie")
    with use_tenant(tenant.id):
        connecteur = FlwConnectorFactory(tenant=tenant, code="fiscal-test")
        FlwCredentialFactory(
            tenant=tenant,
            connector=connecteur,
            kind=FlwCredential.KIND_API_KEY,
            secret=SECRET_DU_TIERS,
        )
        FlwApiKeyFactory(tenant=tenant)
        liaison = FlwLinkFactory(tenant=tenant, connector=connecteur, state=FlwLink.STATE_ACTIVE)
        echange = FlwExchangeFactory(
            tenant=tenant,
            link=liaison,
            operation=OP_PUSH_DOCUMENT,
            state=FlwExchange.STATE_ACCEPTED,
            document_type="accounting.AccMove",
            correlation_key="accounting.AccMove:demo",
        )
        FlwPayloadFactory(tenant=tenant, exchange=echange, body='{"facture": "FA-001"}')

        piece = AccMoveFactory(tenant=tenant, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        piece.fiscal_verdict_raw = VERDICT_BRUT
        piece.save(update_fields=["fiscal_verdict_raw"])

        # Le rapprochement a DEUX faces, et les deux doivent survivre a
        # l'export : le LETTRAGE, qui vit sur la ligne d'ecriture
        # (`AccMoveLine.matching_number`, le champ que T5 partage entre les N
        # encaissements et leur versement), et le RAPPROCHEMENT BANCAIRE, qui
        # relie une ligne de releve a cette ligne d'ecriture.
        ligne_lettree = AccMoveLineFactory(
            tenant=tenant, move=piece, matching_number=NUMERO_DE_LETTRAGE
        )
        AccBankStatementLineFactory(
            tenant=tenant,
            statement_date=dt.date(2026, 3, 1),
            amount_mga=Decimal("250000.0000"),
            direction=AccBankStatementLine.DIRECTION_IN,
            matched_move_line=ligne_lettree,
            state=AccBankStatementLine.STATE_MATCHED,
        )
    return tenant


def _entrees(octets: bytes) -> dict[str, str]:
    """L'archive relue avec la seule bibliotheque standard — c'est tout ce
    dont le successeur du client dispose."""
    archive = zipfile.ZipFile(io.BytesIO(octets))
    return {nom: archive.read(nom).decode("utf-8") for nom in archive.namelist()}


def test_the_archive_carries_links_exchanges_verdicts_and_reconciliations(
    societe_avec_ses_flux: Tenant,
) -> None:
    """**LE critere, ses quatre familles nommees une a une.**

    Les compter separement plutot que verifier « l'archive n'est pas
    vide » : le jour ou la boucle d'export se restreindrait a une liste de
    modeles, c'est UNE famille qui disparaitrait, et un test global ne le
    verrait pas."""
    entrees = _entrees(export_tenant_archive(societe_avec_ses_flux))

    for nom in (
        "data/flows.flwlink.json",
        "data/flows.flwexchange.json",
        "data/flows.flwpayload.json",
        "data/accounting.accmove.json",
        "data/accounting.accmoveline.json",
        "data/accounting.accbankstatementline.json",
    ):
        assert nom in entrees, f"L'archive n'emporte pas {nom} — CON-6 exige l'integralite."

    echanges = json.loads(entrees["data/flows.flwexchange.json"])
    assert len(echanges) == 1
    assert echanges[0]["fields"]["state"] == FlwExchange.STATE_ACCEPTED
    assert echanges[0]["fields"]["correlation_key"] == "accounting.AccMove:demo"

    pieces = json.loads(entrees["data/accounting.accmove.json"])
    assert any(p["fields"]["fiscal_verdict_raw"] == VERDICT_BRUT for p in pieces), (
        "Le verdict du tiers, conserve dans sa forme d'origine (EFA-4), n'est pas dans l'archive."
    )

    ecritures = json.loads(entrees["data/accounting.accmoveline.json"])
    assert any(e["fields"]["matching_number"] == NUMERO_DE_LETTRAGE for e in ecritures), (
        "Le LETTRAGE n'est pas dans l'archive — c'est lui qui dit quelles "
        "pieces un meme versement solde (PAY-5)."
    )

    releves = json.loads(entrees["data/accounting.accbankstatementline.json"])
    assert any(
        r["fields"]["state"] == AccBankStatementLine.STATE_MATCHED
        and r["fields"]["matched_move_line"] is not None
        for r in releves
    ), (
        "Le RAPPROCHEMENT bancaire — ligne de releve vers ligne d'ecriture — "
        "n'est pas dans l'archive."
    )


def test_the_archive_is_readable_without_widehalo(societe_avec_ses_flux: Tenant) -> None:
    """« Format documente et relisible sans WideHalo. »

    Un zip, un manifeste JSON qui NOMME ses tables, un fichier JSON par
    table. Le manifeste est ce qui rend l'archive lisible sans nous : sans
    lui, un successeur devrait deviner qu'un fichier `data/x.y.json`
    correspond a quelque chose."""
    entrees = _entrees(export_tenant_archive(societe_avec_ses_flux))

    assert "manifest.json" in entrees
    manifeste = json.loads(entrees["manifest.json"])
    assert manifeste["tenant_code"] == "CON6"
    assert isinstance(manifeste["format_version"], int)

    annonces = set(manifeste["models"])
    presents = {nom[len("data/") : -len(".json")] for nom in entrees if nom.startswith("data/")}
    assert annonces == presents, (
        "Le manifeste et le contenu divergent : une archive dont l'index "
        "ment n'est pas relisible sans nous."
    )

    for nom, contenu in entrees.items():
        if nom.startswith("data/"):
            assert isinstance(json.loads(contenu), list)


def test_no_third_party_credential_leaves_in_the_archive(
    societe_avec_ses_flux: Tenant,
) -> None:
    """**§13.2, mot pour mot : « table a part, chiffree, JAMAIS EXPORTEE ».**

    Ce test cherche le clair dans les entrees DECOMPRESSEES. La premiere
    version de cette mesure le cherchait dans les octets du zip et rendait
    « aucun secret » alors que `data/flows.flwcredential.json` portait la
    valeur en clair : le zip est compresse.

    Le chiffrement au repos ne protege pas d'un export —
    `EncryptedCharField.from_db_value` dechiffre a la LECTURE, donc les
    objets serialises portent le clair."""
    entrees = _entrees(export_tenant_archive(societe_avec_ses_flux))

    porteurs = [nom for nom, contenu in entrees.items() if SECRET_DU_TIERS in contenu]
    assert not porteurs, (
        f"L'identifiant d'acces au tiers part EN CLAIR dans {porteurs} — "
        "le §13.2 dit « jamais exportee », et une archive se telecharge "
        "depuis un ecran d'administration."
    )

    assert "data/flows.flwcredential.json" in entrees, (
        "La ligne d'identifiant doit rester dans l'archive — le client doit "
        "savoir QUELS raccordements il avait. C'est sa VALEUR qui ne suit pas."
    )
    identifiants = json.loads(entrees["data/flows.flwcredential.json"])
    assert identifiants[0]["fields"]["secret"] == ""
    assert identifiants[0]["fields"]["kind"] == FlwCredential.KIND_API_KEY


def test_no_key_fingerprint_leaves_either(societe_avec_ses_flux: Tenant) -> None:
    """Une empreinte ne se retourne pas — elle se VERIFIE, hors ligne, autant
    de fois qu'on veut.

    Et l'exporter ne sert a rien : `regenerate_secret_token_fields` la
    remplace deja a la reimportation, donc la valeur exportee est morte
    avant d'etre relue."""
    entrees = _entrees(export_tenant_archive(societe_avec_ses_flux))

    cles = json.loads(entrees["data/flows.flwapikey.json"])
    assert cles[0]["fields"]["token_hash"] == ""


def test_the_password_hash_stays_so_a_restore_still_works() -> None:
    """La seule derogation, et son motif.

    `core.User.password` est un condense produit par Django, jamais un
    secret de tiers. Le rediger ferait d'une restauration un tenant dont
    plus personne ne peut se connecter. La derogation est declaree avec son
    motif dans `secret_redaction.EXPORT_ALLOWLIST` ; ce test la tient, pour
    qu'un durcissement futur ne l'emporte pas par mégarde."""
    from apps.core.services.secret_redaction import EXPORT_ALLOWLIST

    assert "core.User.password" in EXPORT_ALLOWLIST
    assert len(EXPORT_ALLOWLIST["core.User.password"]) >= 40
