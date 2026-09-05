"""Garde-fou bloquant (audit §3.6, lot L15) : aucun secret ne dort en clair
dans la base.

L'audit signalait deux champs — `LogServiceProvider.webhook_secret` et
`PrjGuestAccess.token`. En les fermant, un troisieme est apparu :
`UserEmailChangeRequest.token`, qui donne le pouvoir de changer l'identifiant
de connexion d'un compte. Deux corrections ponctuelles auraient laissé la
classe de defaut ouverte ; cette garde la ferme.

Ce qui est en jeu n'est pas l'application mais la BASE et ses SAUVEGARDES.
Une API qui n'expose qu'un `has_webhook_secret: bool` limite la fuite par le
produit et ne protege rien de ce qui circule : un dump, une restauration
chez un prestataire, un poste de developpement avec une copie de production.

**Deux formes acceptees, et le choix entre elles n'est pas libre :**

- **Chiffrement** (`EncryptedCharField`) pour un secret seulement RELU —
  `webhook_secret`, lu une fois pour calculer un HMAC.
- **Empreinte** (nom en `_hash`) pour un secret CHERCHE PAR SA VALEUR —
  les jetons du portail invite et du changement d'e-mail. `EncryptedCharField`
  y est structurellement inapplicable : Fernet n'est pas deterministe, un
  `filter(token=...)` sur un champ chiffre ne correspondrait jamais et le
  mecanisme cesserait de fonctionner en silence.

**Limite assumee** : la detection porte sur le NOM du champ. Un secret
stocke dans un champ nomme `valeur` ou `config` echapperait au motif. C'est
le meme contrat que `sandbox.PII_FIELD_NAMES` et
`object_remap.SECRET_TOKEN_FIELD_NAMES`, deux registres du depot qui
reposent deja sur la convention de nommage — et cette garde verifie en plus
que le second couvre bien tout ce qu'elle-meme trouve, ce qui etait
precisement le point de rupture silencieux lors du passage a l'empreinte.
"""

from __future__ import annotations

import re

# Noms qui designent un secret. `token` au singulier et en fin de nom
# seulement : `monthly_token_budget` et `prompt_tokens_estimate` (apps.ai)
# comptent des jetons de LLM, pas des credentials.
_SECRET_NAME = re.compile(
    r"(^|_)(secret|password|passphrase|api_key|apikey|private_key|credential|token)(_hash)?$",
    re.IGNORECASE,
)

# Exceptions motivees, avec test d'obsolescence.
_ALLOWLIST: dict[str, str] = {
    "core.User.password": (
        "Champ de `django.contrib.auth.models.AbstractBaseUser`, hache par "
        "Django lui-meme (`set_password`/PBKDF2) et jamais stocke en clair. "
        "Le renommer ou le chiffrer casserait l'authentification Django "
        "entiere ; il est deja protege, par un autre mecanisme que ceux de "
        "ce depot."
    ),
}


def _text_secret_fields() -> list[tuple[str, str]]:
    """`(chemin_du_champ, type_du_champ)` pour tout champ TEXTE dont le nom
    designe un secret. Les champs numeriques sont ignores : un entier ne
    porte pas de credential, et les inclure ferait remonter les compteurs de
    jetons LLM."""
    from django.apps import apps as django_apps
    from django.conf import settings
    from django.db import models

    labels = {a.split(".")[-1] for a in settings.INSTALLED_APPS if a.startswith("apps.")}
    found: list[tuple[str, str]] = []
    for model in django_apps.get_models():
        if model._meta.app_label not in labels or ".tests." in model.__module__:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, models.Field) or not field.concrete:
                continue
            if not isinstance(field, models.CharField | models.TextField):
                continue
            if not _SECRET_NAME.search(field.name):
                continue
            path = f"{model._meta.app_label}.{model.__name__}.{field.name}"
            found.append((path, type(field).__name__))
    return sorted(found)


def _is_protected(path: str, field_type: str) -> bool:
    return field_type.startswith("Encrypted") or path.endswith("_hash")


def test_every_secret_field_is_encrypted_or_hashed() -> None:
    offenders = [
        f"{path} ({field_type})"
        for path, field_type in _text_secret_fields()
        if path not in _ALLOWLIST and not _is_protected(path, field_type)
    ]
    assert not offenders, (
        "Secret(s) stocke(s) en clair — chiffrer (`EncryptedCharField`) si le "
        "champ est seulement relu, stocker une empreinte (`*_hash`) s'il est "
        "cherche par sa valeur :\n" + "\n".join(f"  - {line}" for line in offenders)
    )


def test_the_registry_finds_something() -> None:
    """Une garde qui ne regarde aucun champ ne garde rien : si le motif
    cessait de correspondre a quoi que ce soit (renommage massif, registre
    d'applications non charge), les autres assertions passeraient a vide."""
    assert _text_secret_fields(), "Aucun champ de secret trouve — le detecteur est muet."


def test_the_allowlist_has_no_obsolete_entry() -> None:
    known = {path for path, _type in _text_secret_fields()}
    obsolete = sorted(set(_ALLOWLIST) - known)
    assert not obsolete, f"Exception(s) sans champ correspondant : {obsolete}"


def test_every_hashed_secret_is_regenerated_when_a_tenant_is_copied() -> None:
    """Le point de rupture silencieux du lot L15.

    `object_remap.SECRET_TOKEN_FIELD_NAMES` regenere les jetons a l'import
    d'une archive ou au clonage d'un bac a sable — sans quoi deux tenants
    partagent le meme credential resolvable. Ce registre est indexe par NOM
    de champ : le jour ou `token` est devenu `token_hash`, il a cesse de
    trouver quoi que ce soit **sans rien signaler**. Cette assertion est ce
    qui empeche que cela se reproduise au prochain renommage."""
    from apps.core.services.object_remap import SECRET_TOKEN_FIELD_NAMES

    uncovered = sorted(
        path
        for path, field_type in _text_secret_fields()
        if path not in _ALLOWLIST
        and _is_protected(path, field_type)
        and path.rsplit(".", 1)[1] not in SECRET_TOKEN_FIELD_NAMES
        and field_type == "CharField"
    )
    assert not uncovered, (
        "Champ(s) d'empreinte non couvert(s) par "
        "`object_remap.SECRET_TOKEN_FIELD_NAMES` — a l'import d'une archive, "
        "deux tenants partageraient le meme secret :\n"
        + "\n".join(f"  - {line}" for line in uncovered)
    )


def test_the_detector_catches_a_plaintext_secret() -> None:
    """Auto-test du detecteur — sans quoi le garde-fou serait un theatre de
    securite (`test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    assert not _is_protected("app.Model.api_key", "CharField")
    assert not _is_protected("app.Model.webhook_secret", "TextField")
    assert _is_protected("app.Model.webhook_secret", "EncryptedCharField")
    assert _is_protected("app.Model.token_hash", "CharField")
    # Les compteurs de jetons LLM ne doivent jamais entrer dans le motif.
    assert not _SECRET_NAME.search("monthly_token_budget")
    assert not _SECRET_NAME.search("prompt_tokens_estimate")
    assert _SECRET_NAME.search("webhook_secret")
    assert _SECRET_NAME.search("token")
