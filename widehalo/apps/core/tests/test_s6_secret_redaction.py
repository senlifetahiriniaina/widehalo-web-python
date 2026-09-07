"""S6, FLX-8 — le rédacteur de secrets lui-même.

Le critère : « un motif ressemblant à un secret n'apparaît dans aucun
journal, aucune charge utile archivée et aucun message d'erreur affiché à
l'utilisateur. » Ce fichier tient le RÉDACTEUR et la surface JOURNAL ; les
deux autres surfaces sont vérifiées dans `apps/flows/tests/
test_s6_flx8_redaction.py`, là où elles vivent.

**Ce qui existait avant, et ce qui n'existait pas.** Le dépôt savait
chiffrer un secret AU REPOS (`EncryptedCharField`) et savait le vérifier
(`test_secrets_are_never_stored_in_clear.py`). Mais cette garde est une
introspection de MODÈLES : elle regarde la forme des colonnes, et ne
regarde jamais un journal, une trace d'exception, un message d'API ou une
charge utile. `apps/flows/models.py` promettait pourtant la garde de
rédaction à deux endroits, en renvoyant à ce sprint. Elle n'existait pas,
et aucun `redact`, `mask` ou `sanitize` n'existait nulle part dans
`apps/`.

**Ce que le rédacteur ne prétend pas faire, écrit ici pour qu'on ne le lui
reproche pas.** Il ne cherche pas l'entropie. Un seuil d'entropie rédigerait
les UUID, les empreintes, les sommes de contrôle et les identifiants de
commande — c'est-à-dire exactement ce qu'un diagnostic a besoin de lire —
et un journal illisible finit désactivé. Une chaîne aléatoire annoncée par
rien reste donc visible. C'est une limite assumée, pas un oubli.
"""

from __future__ import annotations

import logging

import pytest
from django.conf import settings

from apps.core.logging_filters import SecretRedactingFormatter
from apps.core.services.redaction import (
    MASQUE,
    contains_secret_pattern,
    redact_secrets,
)

# --- Les quatre familles de motifs ---------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        "password=hunter2",
        "PASSWORD = hunter2",
        'api_key: "AKIA0123456789"',
        "{'client_secret': 'zzz'}",
        "token=abc.def",
        "Authorization: Bearer eyJhbGciOiJI",
        "Basic dXNlcjpwYXNzd29yZA==",
        "https://compte:motdepasse@plateforme.mg/api",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4",
        "signature=9f8e7d6c5b4a3",
    ],
)
def test_every_family_of_pattern_is_redacted(texte: str) -> None:
    resultat = redact_secrets(texte)
    assert MASQUE in resultat, f"Non rédigé : {texte!r} -> {resultat!r}"
    assert contains_secret_pattern(texte) is True


@pytest.mark.parametrize(
    "texte",
    [
        "facture FV-2026-0042 montant 4 200 000 Ar",
        "https://dgi.mg/api/v1/facture/01a07c",
        "id=01a07cca-ad1c-79d5-95f4-890a214fbf10 code=200",
        "empreinte 4c9c0dc5f42520f5210e64407b998a2e83f496fe0b1c7d88fcc97daca48a71f9",
        "tenant=FLX7-A operation=OP4 state=accepte",
        "le tiers a répondu 503 après 12,4 s",
    ],
)
def test_nothing_useful_to_a_diagnosis_is_redacted(texte: str) -> None:
    """**Le témoin, et c'est le test qui compte le plus dans ce fichier.**
    Un rédacteur qui masquerait tout satisferait le critère et rendrait
    l'exploitation impossible — un journal illisible est un journal
    désactivé, et une protection désactivée ne protège rien. Empreintes,
    identifiants, codes de retour et montants doivent traverser
    intacts."""
    assert redact_secrets(texte) == texte
    assert contains_secret_pattern(texte) is False


def test_the_surrounding_text_survives_the_redaction() -> None:
    """On rédige la VALEUR, pas la ligne. Effacer le contexte ferait
    disparaître le nom du champ fautif — et le diagnostic avec."""
    assert redact_secrets("password=hunter2, montant=5000") == f"password={MASQUE}, montant=5000"


def test_a_json_payload_stays_valid_json() -> None:
    """Pas cosmétique : le même rédacteur traite la charge utile ARCHIVÉE,
    c'est-à-dire ce qui part chez le tiers. Casser le JSON transformerait
    une protection en refus du tiers, mis à son compte."""
    import json

    redige = redact_secrets('{"api_key": "AKIA0123", "montant": 42000}')
    assert json.loads(redige) == {"api_key": MASQUE, "montant": 42000}


def test_two_masks_in_a_row_are_folded_into_one() -> None:
    """`Authorization: Bearer xyz` est attrapé deux fois — par le schéma
    HTTP et par le couple clef-valeur. Correct, mais illisible."""
    assert redact_secrets("Authorization: Bearer abcdefghijkl") == f"Authorization: {MASQUE}"


def test_the_redactor_never_raises_on_an_odd_input() -> None:
    """Les appelants sont des chemins d'ERREUR. Un rédacteur qui lèverait
    sur un type inattendu remplacerait une fuite par une panne, au pire
    moment."""
    assert redact_secrets(None) == ""
    assert redact_secrets(12345) == "12345"
    assert redact_secrets({"password": "x"}) == "{'password': '" + MASQUE + "'}"


# --- Surface n°1 : les journaux -------------------------------------------------


def test_the_formatter_redacts_the_message() -> None:
    formateur = SecretRedactingFormatter("%(message)s")
    enregistrement = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "appel refusé : api_key=AKIA0123", None, None
    )
    assert MASQUE in formateur.format(enregistrement)
    assert "AKIA0123" not in formateur.format(enregistrement)


def test_the_formatter_redacts_the_traceback_too() -> None:
    """**La raison pour laquelle c'est un formateur et pas un filtre.** Un
    `logging.Filter` voit `record.msg` et `record.args` ; il ne voit pas la
    trace d'exception, qui n'est rendue qu'au formatage. Or
    `logger.exception(...)` est justement la forme sous laquelle un secret
    arrive dans un journal. Un filtre aurait donné l'impression de couvrir
    la surface en laissant passer sa moitié la plus dangereuse."""
    formateur = SecretRedactingFormatter("%(message)s")
    try:
        raise RuntimeError("le tiers refuse : Authorization: Bearer AKIA0123456789")
    except RuntimeError:
        import sys

        enregistrement = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "échec", None, sys.exc_info()
        )
    rendu = formateur.format(enregistrement)
    assert "AKIA0123456789" not in rendu
    assert MASQUE in rendu


def test_every_configured_handler_carries_the_redacting_formatter() -> None:
    """La garde qui rend le réglage opposable : un gestionnaire ajouté plus
    tard sans formateur rouvrirait la fuite en silence, exactement comme un
    modèle ajouté sans RLS. On lit les RÉGLAGES, pas le module de
    journalisation déjà chargé — c'est la configuration qui est la source
    de vérité, et c'est elle qu'une relecture de code modifie."""
    formateurs = settings.LOGGING.get("formatters", {})
    rediges = {
        nom
        for nom, config in formateurs.items()
        if config.get("()") == "apps.core.logging_filters.SecretRedactingFormatter"
    }
    assert rediges, "Aucun formateur rédacteur déclaré dans LOGGING."

    gestionnaires = settings.LOGGING.get("handlers", {})
    assert gestionnaires, "Aucun gestionnaire déclaré : la garde ne garderait rien."
    sans_redaction = {
        nom for nom, config in gestionnaires.items() if config.get("formatter") not in rediges
    }
    assert sans_redaction == set(), (
        f"Gestionnaire(s) sans formateur rédacteur : {sans_redaction}. FLX-8 exige "
        "qu'aucun motif de secret n'apparaisse dans AUCUN journal."
    )
