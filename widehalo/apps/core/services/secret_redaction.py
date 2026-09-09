"""T8 (bloc H, CON-6) — ce qu'une archive de sortie n'emporte pas.

**Le defaut que ce module ferme, et il etait affirme ferme.** Le cahier
§13.2 dit de la table des identifiants de tiers : « table a part, chiffree,
**jamais exportee**, jamais lue par le copilote ». La docstring de
`FlwCredential` reprenait la promesse mot pour mot — « table a part, pour
qu'un export de configuration n'emporte pas les identifiants ». Elle etait
fausse : `tenant_export.export_tenant_archive` parcourt
`iter_concrete_basemodel_subclasses()`, c'est-a-dire TOUTE sous-classe
concrete de `BaseModel`, et `FlwCredential` en est une.

**Pire que « exportee » : exportee EN CLAIR.**
`EncryptedCharField.from_db_value` dechiffre a la lecture. Les instances que
le serialiseur recoit portent donc la valeur en clair, et c'est elle qui
part dans le JSON. Le chiffrement au repos protege la BASE, jamais
l'ARCHIVE — et l'archive, elle, se telecharge depuis un ecran
d'administration.

Mesure, avant correction, sur un tenant portant un seul identifiant :
`data/flows.flwcredential.json` contenait
`"secret": "<le clair>"`.

**Deux familles redigees, pour deux raisons distinctes.**

- Les champs CHIFFRES (`EncryptedCharField`) : `FlwCredential.secret` et
  `LogServiceProvider.webhook_secret`. Ils partaient en clair. C'est la
  fuite.
- Les champs d'EMPREINTE (`*_hash`) : `FlwApiKey.token_hash`,
  `PrjGuestAccess.token_hash`, `UserEmailChangeRequest.token_hash`. Une
  empreinte ne se retourne pas, mais elle permet a qui detient l'archive de
  VERIFIER des candidats hors ligne, autant de fois qu'il veut. Et les
  exporter ne sert a rien : `object_remap.regenerate_secret_token_fields`
  les regenere deja a l'import, donc la valeur exportee est morte avant
  meme d'etre relue.

**La seule exception, et son motif.** `core.User.password` est un condense
PBKDF2 produit par Django lui-meme, jamais un secret de tiers, et c'est
l'unique champ dont l'absence casserait une RESTAURATION : un tenant
restaure dont personne ne peut plus se connecter n'est pas restaure. Il est
donc conserve, comme `tests/architecture/
test_secrets_are_never_stored_in_clear.py` le dispense deja de sa propre
regle, et pour la meme raison — il est protege par un autre mecanisme.

**Le prix assume, ecrit plutot que decouvert.** Une archive ne restaure plus
les identifiants de connecteur : apres restauration, ils sont a resaisir par
l'assistant d'enrolement. C'est exactement ce que « jamais exportee »
coute, et le cahier le demande sans reserve. L'alternative — un drapeau
`include_secrets` — laisserait la fuite vivre par defaut sous couvert de
l'avoir nommee.
"""

from __future__ import annotations

import re
from typing import Any

from django.db import models

#: Les noms qui designent un secret. Volontairement IDENTIQUE dans son
#: intention a celui de `test_secrets_are_never_stored_in_clear.py`, et
#: volontairement ecrit deux fois : la garde doit pouvoir contredire ce
#: module, ce qu'elle ne pourrait plus faire si elle importait sa propre
#: reference d'ici (lecon F60 du lot T6 — un jeu ferme ne se verifie jamais
#: contre sa propre source).
_SECRET_NAME = re.compile(
    r"(^|_)(secret|password|passphrase|api_key|apikey|private_key|credential|token)(_hash)?$",
    re.IGNORECASE,
)

#: Chemin `app.Modele.champ` conserve dans l'archive, avec son motif. Une
#: entree sans motif serait une derogation muette.
EXPORT_ALLOWLIST: dict[str, str] = {
    "core.User.password": (
        "Condense PBKDF2 produit par Django, jamais un secret de tiers. "
        "C'est le seul champ dont la redaction casserait la RESTAURATION : "
        "un tenant restaure dont plus aucun utilisateur ne peut se "
        "connecter n'est pas restaure."
    ),
}


def secret_field_names(model: type[models.Model]) -> tuple[str, ...]:
    """Les champs TEXTE de ce modele dont le nom designe un secret, hors
    derogation.

    Texte seulement : un entier ne porte pas d'identifiant, et inclure les
    champs numeriques ferait remonter les compteurs de jetons de LLM
    (`monthly_token_budget`), qui comptent des jetons de modele et non des
    credentials."""
    noms: list[str] = []
    for field in model._meta.get_fields():
        if not isinstance(field, models.Field) or not field.concrete:
            continue
        if not isinstance(field, models.CharField | models.TextField):
            continue
        if not _SECRET_NAME.search(field.name):
            continue
        chemin = f"{model._meta.app_label}.{model.__name__}.{field.name}"
        if chemin in EXPORT_ALLOWLIST:
            continue
        noms.append(field.name)
    return tuple(noms)


def redact_secret_fields(instance: Any) -> tuple[str, ...]:  # noqa: ANN401
    """Vide EN MEMOIRE les champs de secret de l'instance, et rend leurs
    noms.

    **En memoire, et jamais sauvegarde** : l'appelant serialise l'objet
    redige et jette l'instance. Ecrire la redaction en base detruirait
    l'identifiant du client au lieu de le tenir hors de l'archive.

    La chaine vide plutot que `None` : les six champs concernes sont tous
    `null=False`, et un `None` ferait echouer la reimportation sur une
    contrainte de base plutot que sur une regle lisible."""
    redires = secret_field_names(type(instance))
    for nom in redires:
        setattr(instance, nom, "")
    return redires


__all__ = ["EXPORT_ALLOWLIST", "redact_secret_fields", "secret_field_names"]
