"""Champ chiffre au repos, minimal et reutilisable — construit pour ce
chantier (`presence`, RG-PRS-9 : CIN/motifs medicaux "sensibles") faute de
tout patron existant dans le depot (`EncryptedField`/`django-cryptography`/
`Fernet` : aucune occurrence avant ce fichier, verifie par recherche
exhaustive). `cryptography` est deja une dependance transitive du projet
(django-otp/ninja-jwt) — aucune nouvelle dependance ajoutee.

Cle : derivee de `settings.SECRET_KEY` via SHA-256 -> base64 urlsafe (32
octets, format attendu par `Fernet`). Choix documente : pas de cle dediee
distincte en V1 (simplification assumee, disclosed) — une vraie rotation de
cle necessiterait un `FIELD_ENCRYPTION_KEY` separe + un mecanisme de
re-chiffrement au changement de cle, hors perimetre de ce chantier. Le
risque residuel (`SECRET_KEY` compromise expose aussi ce champ) est le meme
compromis que celui deja fait pour la signature des sessions/JWT dans ce
depot.

Recherche en base sur ce champ est impossible (valeur chiffree, jamais
deterministe) — n'utiliser `EncryptedCharField` que pour des champs jamais
filtres/recherches par l'ORM (ex. `prs_employee.cin`), jamais pour une cle
d'unicite ou un champ de recherche."""

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


class EncryptedCharField(models.CharField):  # type: ignore[type-arg]
    # CharField n'est pas subscriptable a l'execution avec ces versions de
    # Django/django-stubs (verifie empiriquement) — l'annotation generique
    # complete n'est donc pas exploitable ici, contrairement a
    # `TenantManager[_M]` (base.py) qui, lui, fonctionne. Ignore cible,
    # documente.
    """Chiffre/dechiffre de maniere transparente a l'ecriture/lecture ORM.
    `max_length` s'applique a la valeur EN CLAIR (le stockage chiffre est
    plus long — la colonne DB n'a pas de contrainte de longueur stricte,
    cf. `db_type`)."""

    def db_type(self, connection: Any) -> str:  # noqa: ANN401
        return "text"

    def get_prep_value(self, value: Any) -> Any:  # noqa: ANN401
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        token = _fernet().encrypt(value.encode("utf-8"))
        return token.decode("ascii")

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:  # noqa: ANN401
        if value in (None, ""):
            return value
        try:
            return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken:
            # Valeur deja en clair (ex. donnee de fixture ancienne) ou cle
            # changee — ne jamais lever au chargement, degrader visiblement
            # plutot que planter tout un queryset.
            return value

    def to_python(self, value: Any) -> Any:  # noqa: ANN401
        if isinstance(value, str) or value is None:
            return value
        return str(value)


class EncryptedDecimalField(models.DecimalField):  # type: ignore[type-arg]
    """Variante `Decimal` de `EncryptedCharField`, ajoutee pour le chantier
    `payroll` (RG-PAY-9/enrichissement "Chiffrement AES-256 des donnees
    salariales") — le champ chiffre stocke la valeur decimale serialisee en
    chaine (`str(Decimal)`, jamais `float`, coherent avec la convention
    "argent en Decimal" du depot), au meme format Fernet que
    `EncryptedCharField`. Utilise par `apps.payroll.models.PayPayslip` pour
    les montants individuellement consultables hors liste (ex. `net_to_pay`)
    quand une confidentialite renforcee au niveau colonne SQL est demandee
    en plus du controle applicatif RG-PAY-9 (defense en profondeur — la
    encore un compromis assume, cf. docstring `EncryptedCharField` sur
    l'absence de cle dediee/rotation en V1)."""

    def db_type(self, connection: Any) -> str:  # noqa: ANN401
        return "text"

    def get_prep_value(self, value: Any) -> Any:  # noqa: ANN401
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        token = _fernet().encrypt(str(value).encode("utf-8"))
        return token.decode("ascii")

    def get_db_prep_save(self, value: Any, connection: Any) -> Any:  # noqa: ANN401
        # `DecimalField.get_db_prep_save` (classe parente) contourne
        # normalement `get_prep_value`/`get_db_prep_value` en appelant
        # directement `connection.ops.adapt_decimalfield_value` — ce qui
        # ecrirait la valeur EN CLAIR dans la colonne "text" malgre
        # `get_prep_value` ci-dessus (jamais invoque dans ce chemin).
        # Override explicite pour repasser par le chiffrement, seule
        # difference avec le comportement standard de `DecimalField`.
        return self.get_prep_value(value)

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:  # noqa: ANN401
        if value in (None, ""):
            return value
        try:
            decrypted = _fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken:
            # Meme discipline degradee que EncryptedCharField : valeur deja
            # en clair ou cle changee, ne jamais planter tout un queryset.
            decrypted = value
        try:
            return Decimal(decrypted)
        except InvalidOperation:
            return None

    def to_python(self, value: Any) -> Any:  # noqa: ANN401
        if value is None or isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
