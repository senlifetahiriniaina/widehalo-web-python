"""Garde T8 (bloc H, CON-6 / §13.2) : aucun secret ne sort dans une archive.

**Le defaut mesure que cette garde ferme.** Le cahier §13.2 dit de la table
des identifiants de tiers : « table a part, chiffree, **jamais exportee** ».
La docstring de `FlwCredential` reprenait la promesse. Elle etait fausse :
`export_tenant_archive` parcourt TOUTE sous-classe concrete de `BaseModel`,
et `EncryptedCharField` dechiffre a la LECTURE — le clair partait donc dans
`data/flows.flwcredential.json`, dans une archive qui se telecharge depuis
un ecran d'administration.

**Pourquoi une garde et pas seulement le test de CON-6.** Le test de CON-6
(`apps/core/tests/test_con6_export_garantie_de_sortie.py`) exerce les champs
qui existent AUJOURD'HUI. Il ne dira rien du septieme champ de secret ajoute
dans six mois. Ce fichier ferme la CLASSE : tout champ dont le nom designe
un secret est redige a l'export, ou bien figure dans la derogation avec son
motif. C'est le pendant, pour les ARCHIVES, de ce que
`test_secrets_are_never_written_to_a_log.py` fait pour les JOURNAUX et
`test_secrets_are_never_stored_in_clear.py` pour la BASE — les trois
surfaces sont distinctes, et fermer l'une n'a jamais ferme les autres.

**La liste litterale ci-dessous n'est pas redondante.** Elle est
INDEPENDANTE du registre qu'elle surveille — c'est la lecon F60 du lot T6,
ou une falsification n'avait pas mordu parce que le test comparait un jeu
ferme a sa propre source. Si `secret_redaction._SECRET_NAME` cessait de
reconnaitre `secret`, la detection generique deviendrait vide et passerait
sans rien dire ; la liste litterale, elle, tombe.
"""

from __future__ import annotations

import re

from apps.core.services.secret_redaction import (
    EXPORT_ALLOWLIST,
    redact_secret_fields,
    secret_field_names,
)
from django.apps import apps as django_apps
from django.conf import settings
from django.db import models

#: Ecrit a la main, a partir de la mesure faite au lot T8. Le format est
#: `app.Modele.champ`. Toute entree retiree du code sans etre retiree d'ici
#: fait tomber cette garde, et c'est le but.
CHAMPS_DE_SECRET_CONNUS = {
    "core.User.password",
    "core.UserEmailChangeRequest.token_hash",
    "flows.FlwApiKey.token_hash",
    "flows.FlwCredential.secret",
    "logistics.LogServiceProvider.webhook_secret",
    "projects.PrjGuestAccess.token_hash",
}

_MOTIF_INDEPENDANT = re.compile(
    r"(^|_)(secret|password|passphrase|api_key|apikey|private_key|credential|token)(_hash)?$",
    re.IGNORECASE,
)


def _champs_texte_de_secret() -> set[str]:
    """Balayage par un motif ECRIT ICI, jamais importe du module surveille."""
    labels = {a.split(".")[-1] for a in settings.INSTALLED_APPS if a.startswith("apps.")}
    trouves: set[str] = set()
    for model in django_apps.get_models():
        if model._meta.app_label not in labels or ".tests." in model.__module__:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, models.Field) or not field.concrete:
                continue
            if not isinstance(field, models.CharField | models.TextField):
                continue
            if _MOTIF_INDEPENDANT.search(field.name):
                trouves.add(f"{model._meta.app_label}.{model.__name__}.{field.name}")
    return trouves


def test_the_known_secret_fields_are_still_the_ones_measured() -> None:
    """Un champ de secret NEUF doit passer par ici, consciemment.

    Sans ce test, un septieme champ ajoute demain serait redige en silence
    (bonne nouvelle) ou oublie en silence (mauvaise) — et personne ne
    saurait lequel des deux."""
    trouves = _champs_texte_de_secret()
    assert trouves == CHAMPS_DE_SECRET_CONNUS, (
        "Le jeu des champs de secret a change. Ajouter le champ neuf a "
        "`CHAMPS_DE_SECRET_CONNUS` APRES avoir verifie qu'il est bien "
        f"redige a l'export.\n  En trop : {sorted(trouves - CHAMPS_DE_SECRET_CONNUS)}"
        f"\n  Disparus : {sorted(CHAMPS_DE_SECRET_CONNUS - trouves)}"
    )


def test_every_secret_field_is_redacted_or_waived_with_a_written_reason() -> None:
    """La classe entiere, pas les six cas d'aujourd'hui."""
    for chemin in sorted(_champs_texte_de_secret()):
        app_label, nom_modele, nom_champ = chemin.split(".")
        model = django_apps.get_model(app_label, nom_modele)
        redige = nom_champ in secret_field_names(model)
        derogé = chemin in EXPORT_ALLOWLIST
        assert redige or derogé, (
            f"« {chemin} » part dans l'archive de garantie de sortie. Le "
            "§13.2 dit « jamais exportee » : soit il est redige, soit il "
            "figure dans `EXPORT_ALLOWLIST` avec son motif."
        )
        assert not (redige and derogé), (
            f"« {chemin} » est a la fois redige et dispense de l'etre — "
            "la derogation ne dit donc rien de vrai."
        )


def test_every_waiver_carries_a_reason_and_still_designates_a_real_field() -> None:
    """Une derogation muette, ou qui vise un champ disparu, est pire que pas
    de derogation : elle donne l'impression d'un arbitrage rendu."""
    connus = _champs_texte_de_secret()
    for chemin, motif in EXPORT_ALLOWLIST.items():
        assert chemin in connus, (
            f"La derogation « {chemin} » ne designe plus aucun champ — "
            "a retirer plutot qu'a garder."
        )
        assert len(motif) >= 40, (
            f"Motif trop court pour « {chemin} » : une derogation de "
            "securite s'explique, elle ne se decrete pas."
        )


def test_redaction_empties_the_field_without_touching_the_database() -> None:
    """La redaction agit EN MEMOIRE — l'archive ne porte pas le secret, et
    le client ne le perd pas.

    Sans instance sauvegardee : c'est precisement ce qu'on veut prouver."""
    from apps.flows.models import FlwCredential

    instance = FlwCredential(
        label="test", kind=FlwCredential.KIND_API_KEY, secret="a-ne-pas-sortir"
    )
    rediges = redact_secret_fields(instance)

    assert "secret" in rediges
    assert instance.secret == ""
    # `pk is None` ne dirait rien ici : `BaseModel` attribue son UUID7 des
    # l'instanciation. `_state.adding` est l'etat qui distingue reellement
    # un objet jamais ecrit d'un objet relu.
    assert instance._state.adding, "La redaction ne doit jamais avoir sauvegarde quoi que ce soit."
