"""Les huit operations canoniques du hub de flux — jeu FERME (cahier §4.1).

**Pourquoi fermer, et pourquoi maintenant.** `FlwConnector.supported_
operations` annoncait deja, en commentaire, que « l'executeur y lit ce
qu'il a le droit de demander » et qu'« un adaptateur qui n'annonce pas une
operation ne se la verra jamais confier ». C'etait faux : un `JSONField`
libre, un `CharField` libre sur trois modeles, et personne pour lire ni
l'un ni l'autre. Le depot avait donc, a cet endroit precis, exactement le
defaut qu'il corrige partout ailleurs — une configuration decorative.

Le cahier ne laisse aucune marge sur ce point : « huit operations
canoniques et quatre modes de declenchement couvrent l'integralite des
liaisons identifiees » (decision structurante n°2), et « un connecteur se
decrit alors par le SOUS-ENSEMBLE d'operations qu'il implemente, et rien
de plus » (§4.1). Un sous-ensemble suppose un ensemble ; sans jeu ferme,
`supported_operations` n'est pas un sous-ensemble, c'est une liste de
chaines.

**Le sens fait partie de la definition, pas du commentaire.** §4.1 se
termine sur « les cinq premieres operations ecrivent vers l'exterieur, les
trois dernieres lisent ou recoivent », et en tire explicitement la forme du
modele de donnees : « une seule table d'echange porte les huit, avec un
attribut de sens et un attribut d'operation ». Deux attributs qui se
contredisent — un OP7 sortant, une notification entrante qu'on emet —
n'ont aucun sens metier, et la table les accepterait sans broncher. Le
sens de chaque operation est donc une DONNEE ici, opposable a la creation
de l'echange, plutot qu'une phrase du cahier que personne ne relit.

**OP8 est sortante et pourtant en lecture**, et c'est la seule : elle
interroge un referentiel. La distinction sortant/entrant que porte
`FlwExchange.direction` est celle de QUI APPELLE, pas de qui lit — c'est
nous qui composons le numero. La ranger avec OP1-OP5 est donc correct pour
le sens, et le tableau du cahier le confirme en la notant « Sortant,
lecture ».

Meme discipline que les six familles d'erreur (§10.3), les six
transformations de correspondance (§4.3, axe A2) et les six unites de
cout : des constantes, une validation a l'enregistrement, et une garde qui
refuse la neuvieme.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

#: OP1 — Pousser un document. Sortant, accuse technique.
OP_PUSH_DOCUMENT = "OP1"
#: OP2 — Publier un jeu de donnees. Sortant, accuse technique.
OP_PUBLISH_DATASET = "OP2"
#: OP3 — Deposer un fichier. Sortant, emplacement en retour.
OP_DROP_FILE = "OP3"
#: OP4 — Soumettre pour validation. Sortant, avec verdict differe.
OP_SUBMIT_FOR_VERDICT = "OP4"
#: OP5 — Initier un mouvement d'argent. Sortant, confirmation differee.
OP_INITIATE_PAYMENT = "OP5"
#: OP6 — Ingerer un lot. ENTRANT, compte rendu en retour.
OP_INGEST_BATCH = "OP6"
#: OP7 — Recevoir un evenement. ENTRANT, reponse immediate.
OP_RECEIVE_EVENT = "OP7"
#: OP8 — Interroger un referentiel. Sortant en lecture, synchrone.
OP_QUERY_REFERENCE = "OP8"

OPERATION_CHOICES = [
    (OP_PUSH_DOCUMENT, _("OP1 — Pousser un document")),
    (OP_PUBLISH_DATASET, _("OP2 — Publier un jeu de données")),
    (OP_DROP_FILE, _("OP3 — Déposer un fichier")),
    (OP_SUBMIT_FOR_VERDICT, _("OP4 — Soumettre pour validation")),
    (OP_INITIATE_PAYMENT, _("OP5 — Initier un mouvement d'argent")),
    (OP_INGEST_BATCH, _("OP6 — Ingérer un lot")),
    (OP_RECEIVE_EVENT, _("OP7 — Recevoir un événement")),
    (OP_QUERY_REFERENCE, _("OP8 — Interroger un référentiel")),
]

#: Le jeu ferme lui-meme. Dérivé des choix, jamais recopié : deux listes
#: recopiées divergent, et c'est la divergence qui ferait passer une
#: neuvième opération.
OPERATION_CODES = frozenset(code for code, _label in OPERATION_CHOICES)

#: Les operations dont l'echange est ENTRANT. Les six autres sont
#: sortantes. Ecrit en negatif — l'exception plutot que la regle — parce
#: qu'une neuvieme operation oubliee ici serait sortante par defaut, et
#: qu'une operation sortante par erreur est retenue par la vidange, alors
#: qu'une entrante par erreur serait DRAINEE, c'est-a-dire appelee.
INBOUND_OPERATIONS = frozenset({OP_INGEST_BATCH, OP_RECEIVE_EVENT})


def is_inbound_operation(operation: str) -> bool:
    return operation in INBOUND_OPERATIONS


def validate_operation(operation: str) -> str:
    """Rend l'operation si elle appartient au jeu ferme, leve sinon.

    Renvoie la valeur plutot que `None` pour que l'appelant puisse ecrire
    `operation=validate_operation(x)` : une validation dont on peut oublier
    d'utiliser le resultat finit toujours par etre appelee sans que sa
    valeur serve."""
    if operation not in OPERATION_CODES:
        raise ValidationError(
            _(
                "« %(operation)s » n'est pas une des huit opérations canoniques "
                "(%(connues)s). Le cahier les tient pour limitatives : une neuvième "
                "opération est un adaptateur qui déborde de son rôle, pas un besoin "
                "nouveau."
            )
            % {"operation": operation, "connues": ", ".join(sorted(OPERATION_CODES))}
        )
    return operation


def validate_supported_operations(value: object) -> None:
    """Validateur de champ pour `FlwConnector.supported_operations`.

    Refuse ce qui n'est pas une liste, ce qui contient un doublon, et ce
    qui nomme une operation inconnue. Le doublon compte : `supported_
    operations` est un SOUS-ENSEMBLE au sens du cahier, et une liste qui
    repete OP1 laisse croire a une capacite double la ou il n'y en a
    qu'une."""
    if not isinstance(value, list):
        raise ValidationError(
            _("Les opérations supportées se déclarent en liste, pas en %(type)s.")
            % {"type": type(value).__name__}
        )
    inconnues = [item for item in value if item not in OPERATION_CODES]
    if inconnues:
        raise ValidationError(
            _(
                "Opération(s) inconnue(s) : %(inconnues)s. Les huit opérations "
                "canoniques sont %(connues)s."
            )
            % {
                "inconnues": ", ".join(map(str, inconnues)),
                "connues": ", ".join(sorted(OPERATION_CODES)),
            }
        )
    if len(set(value)) != len(value):
        raise ValidationError(_("Une opération déclarée deux fois : %(liste)s.") % {"liste": value})


__all__ = [
    "INBOUND_OPERATIONS",
    "OPERATION_CHOICES",
    "OPERATION_CODES",
    "OP_DROP_FILE",
    "OP_INGEST_BATCH",
    "OP_INITIATE_PAYMENT",
    "OP_PUBLISH_DATASET",
    "OP_PUSH_DOCUMENT",
    "OP_QUERY_REFERENCE",
    "OP_RECEIVE_EVENT",
    "OP_SUBMIT_FOR_VERDICT",
    "is_inbound_operation",
    "validate_operation",
    "validate_supported_operations",
]
