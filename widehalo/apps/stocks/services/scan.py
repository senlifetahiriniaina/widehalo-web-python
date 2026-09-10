"""STK-9 (Phase 3 §7.3, sprint A6, mode dégradé terrain) : point d'entrée
unique et idempotent de la synchronisation d'une ligne de réception
scannée depuis l'écran magasinier (`templates/stocks/tw-scan.html`) — que
la ligne soit envoyée en ligne ou rejouée après une coupure réseau. Même
patron, très directement calqué, que
`apps.pos.services.orders.sync_order` (le protocole hors ligne du POS est
réutilisé, pas réinventé — cahier, « H19 »).

Chaque tentative de synchronisation (acceptée/doublon/rejetée) est
journalisée via `apps.core.services.audit.log_action` (`AuditLog`, déjà
existant, immuable en base) plutôt que par un nouveau modèle dédié à la
`apps.pos.models.PosSyncLog` : `stocks` était déjà à 290/290 modèles au
moment de ce sprint (`tests/architecture/test_budget.py::
test_model_budget_not_exceeded`), plafond qui ne se relève pas sans
décision explicite du commanditaire — réutiliser le journal d'audit
transversal est le choix qui respecte ce garde-fou plutôt que de le
contourner."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_base_uom_code, get_variant_id_by_ean13
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.audit import log_action
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.barcodes import lookup_by_barcode
from apps.stocks.services.moves import create_move, validate_move

OUTCOME_ACCEPTED = "accepted"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_REJECTED = "rejected"

ACTION_ACCEPTED = "stocks.scan.accepted"
ACTION_DUPLICATE = "stocks.scan.duplicate"
ACTION_REJECTED = "stocks.scan.rejected"

ACTION_PUTAWAY_ACCEPTED = "stocks.scan.putaway.accepted"
ACTION_PUTAWAY_DUPLICATE = "stocks.scan.putaway.duplicate"
ACTION_PUTAWAY_REJECTED = "stocks.scan.putaway.rejected"

#: Les quatre actions de l'ecran magasinier (cahier §13.1 : « quatre
#: actions au maximum : recevoir, ranger, prelever, compter »). Le
#: PLAFOND fait partie du critere : ajouter une cinquieme tuile le viole,
#: meme si le persona du §3.1 cite cinq ecrans. C'est pourquoi ce jeu est
#: ferme et garde, plutot qu'une liste que l'on allonge.
SCAN_MODE_RECEVOIR = "receive"
SCAN_MODE_RANGER = "putaway"
SCAN_MODE_PRELEVER = "pick"
SCAN_MODE_COMPTER = "count"

SCAN_MODES = (
    SCAN_MODE_RECEVOIR,
    SCAN_MODE_RANGER,
    SCAN_MODE_PRELEVER,
    SCAN_MODE_COMPTER,
)

#: Ceux qui sont reellement cables. **Une tuile qui bascule vers un
#: panneau vide est pire qu'une tuile marquee indisponible** : le
#: magasinier essaie, ne comprend pas, et recommence. Ce jeu retrecira a
#: mesure que les actions arrivent, et l'ecart entre les deux tuples est
#: exactement ce que l'ecran doit dire.
SCAN_MODES_DISPONIBLES = (SCAN_MODE_RECEVOIR, SCAN_MODE_RANGER)

#: Les actions qui alimentent le panneau « a traiter » de l'ecran. Un
#: tuple plutot qu'un litteral repete : une action de scan ajoutee sans
#: etre inscrite ici produirait des rejets que personne ne verrait — la
#: reconciliation explicite du §7.3 tomberait en silence.
REJECTED_ACTIONS = (ACTION_REJECTED, ACTION_PUTAWAY_REJECTED)


#: Repli quand l'article ne declare aucune unite de base. `"pc"` est
#: l'unite la plus courante du referentiel et celle que le gabarit imposait
#: jusqu'ici a TOUT article : le repli ne degrade donc rien par rapport a
#: l'existant, et il ne s'applique qu'a un article mal configure.
UOM_PAR_DEFAUT = "pc"


def resolve_scanned_location(tenant: Tenant, raw: str) -> StkLocation | None:
    """L'emplacement designe par un code scanne ou saisi.

    Un lecteur de codes-barres est vu comme un clavier — une valeur scannee
    et une saisie manuelle du CODE produisent la meme chaine (cahier §9.1),
    donc la meme resolution : code-barres d'abord, code d'emplacement en
    repli, restreint aux emplacements INTERNES (un magasinier ne travaille
    jamais directement sur un emplacement virtuel).

    **Cette fonction vivait dans la vue ; elle a du descendre ici, et la
    raison est le mode degrade.** Une reception resout son emplacement de
    destination UNE FOIS, au chargement de l'ecran, parce qu'il ne change
    pas de la journee. Un rangement change d'etagere a chaque palette : la
    tablette hors ligne n'a rien pour resoudre un code, et doit donc
    l'envoyer BRUT. La resolution a lieu au moment du rejeu, cote serveur,
    ou un code introuvable devient un rejet journalise plutot qu'une ligne
    perdue."""
    if not raw:
        return None
    location = lookup_by_barcode(tenant, raw)
    if location is not None:
        return location
    return StkLocation.objects.filter(
        tenant=tenant, code=raw, type=StkLocation.TYPE_INTERNE, is_active=True
    ).first()


def resolve_scan_uom(variant_id: object) -> str:
    """L'unite de stock d'un article scanne, lue sur l'article.

    Jamais recue du client : une tablette hors ligne ne connait pas
    l'unite d'un code-barres qu'elle vient de lire, et un champ cache est
    une valeur que l'appelant peut mentir."""
    return get_variant_base_uom_code(variant_id) or UOM_PAR_DEFAUT


def sync_scan_reception_line(
    tenant: Tenant,
    *,
    client_uuid: UUID,
    location_from: StkLocation,
    location_to: StkLocation,
    ean13: str,
    qty: Decimal,
    date: dt.date,
    operator: User | None = None,
) -> tuple[StkMove | None, str]:
    """`client_uuid` déjà connu (`StkMove` existant) => AUCUN nouveau
    mouvement, aucun doublon (STK-9 : « produit exactement trente
    mouvements, sans doublon ni perte ») : le mouvement existant est
    retourné tel quel, un `AuditLog` "duplicate" est journalisé. Toute
    autre erreur (code-barres article inconnu, garde RG-STK-10/lot bloqué
    de `create_move`/`validate_move`...) est journalisée "rejected" AVANT
    d'être relevée telle quelle à l'appelant — c'est ce journal qui
    alimente le panneau « à traiter » de l'écran (cahier §7.3 : « la
    ligne concernée est présentée pour arbitrage plutôt qu'appliquée en
    force ou rejetée en silence »).

    **Volontairement PAS `@transaction.atomic` sur cette fonction
    elle-même** — même piège/même solution que `sync_order` (cf. son
    docstring) : seule la construction du mouvement doit être annulée en
    cas d'échec, jamais le `log_action()` de la branche `except`, qui
    doit survivre au `raise` final. Un décorateur englobant annulerait ce
    dernier avec le reste dès que l'exception se propage hors de la
    fonction.

    `unit_cost_mga=0` par défaut (une réception au scan sans clavier n'a
    pas de coût de revient saisissable dans ce sprint — rapprochement
    ultérieur avec le bon de commande, hors périmètre explicite d'A6).

    **L'unité n'est plus un paramètre, et c'est une correction.** Le
    gabarit l'envoyait dans un champ caché figé à `"pc"` : toute réception
    au mètre ou au kilo était donc enregistrée en pièces. Elle se lit
    désormais sur l'article lui-même, une fois le code-barres résolu —
    c'est-à-dire au seul endroit qui la connaisse. Deux bénéfices, et le
    second compte autant que le premier : la tablette hors ligne n'a pas à
    connaître l'unité d'un article qu'elle vient de scanner, et une valeur
    que le client pouvait mentir disparaît de la charge utile."""
    existing = StkMove.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
    if existing is not None:
        log_action(
            ACTION_DUPLICATE,
            actor=operator,
            obj=existing,
            metadata={
                "client_uuid": str(client_uuid),
                "detail": _("Ligne déjà synchronisée, rejeu ignoré."),
            },
        )
        return existing, OUTCOME_DUPLICATE

    try:
        with transaction.atomic():
            variant_id = get_variant_id_by_ean13(ean13)
            if variant_id is None:
                raise ValidationError(
                    _("Code-barres article inconnu : %(ean13)s") % {"ean13": ean13}
                )
            move = create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=qty,
                uom=resolve_scan_uom(variant_id),
                location_from=location_from,
                location_to=location_to,
                date=date,
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal(0),
                operator=operator,
                client_uuid=client_uuid,
            )
            validate_move(move)
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        log_action(
            ACTION_REJECTED,
            actor=operator,
            metadata={"client_uuid": str(client_uuid), "detail": detail},
        )
        raise

    log_action(
        ACTION_ACCEPTED,
        actor=operator,
        obj=move,
        metadata={"client_uuid": str(client_uuid), "detail": ""},
    )
    return move, OUTCOME_ACCEPTED


def sync_scan_putaway_line(
    tenant: Tenant,
    *,
    client_uuid: UUID,
    location_from_code: str,
    location_to_code: str,
    ean13: str,
    qty: Decimal,
    date: dt.date,
    operator: User | None = None,
) -> tuple[StkMove | None, str]:
    """Ranger : deplacer une quantite d'une etagere vers une autre.

    **Un transfert est UN mouvement a deux emplacements, jamais deux
    mouvements apparies** (cahier §12.1) — c'est ce qui garantit qu'il ne
    peut pas etre a moitie realise, y compris apres une coupure reseau
    (STK-5). Le service se contente donc d'un `create_move` suivi de son
    `validate_move` : il n'y a rien a orchestrer, et toute orchestration
    ajoutee ici ouvrirait precisement le trou que le critere ferme.

    **Les emplacements arrivent en CODE, pas en identifiant.** Une
    reception resout sa destination une fois pour la journee ; un rangement
    change d'etagere a chaque palette, et la tablette hors ligne n'a rien
    pour resoudre un code. La resolution a donc lieu ici, au rejeu. Un code
    introuvable devient un rejet journalise qui reparait dans « a
    traiter » — la reconciliation explicite du §7.3, jamais une ligne
    perdue.

    **`unit_cost_mga` n'est pas renseigne, et ce n'est pas un oubli.** Pour
    un mouvement d'un emplacement interne vers un autre, `validate_move`
    reprend le cout unitaire du quant source et ignore celui du mouvement :
    ranger une palette ne change pas ce qu'elle vaut.

    **Volontairement PAS `@transaction.atomic` sur cette fonction** — meme
    piege que `sync_scan_reception_line` : le `log_action` de la branche
    d'echec doit survivre au `raise` final, et un decorateur englobant
    l'annulerait avec le reste."""
    existing = StkMove.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
    if existing is not None:
        log_action(
            ACTION_PUTAWAY_DUPLICATE,
            actor=operator,
            obj=existing,
            metadata={
                "client_uuid": str(client_uuid),
                "detail": _("Rangement déjà synchronisé, rejeu ignoré."),
            },
        )
        return existing, OUTCOME_DUPLICATE

    try:
        with transaction.atomic():
            location_from = _emplacement_interne(tenant, location_from_code, _("départ"))
            location_to = _emplacement_interne(tenant, location_to_code, _("destination"))
            variant_id = get_variant_id_by_ean13(ean13)
            if variant_id is None:
                raise ValidationError(
                    _("Code-barres article inconnu : %(ean13)s") % {"ean13": ean13}
                )
            move = create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=qty,
                uom=resolve_scan_uom(variant_id),
                location_from=location_from,
                location_to=location_to,
                date=date,
                move_type=StkMove.TYPE_TRANSFERT_INTERNE,
                operator=operator,
                client_uuid=client_uuid,
            )
            validate_move(move)
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        log_action(
            ACTION_PUTAWAY_REJECTED,
            actor=operator,
            metadata={
                "client_uuid": str(client_uuid),
                "detail": detail,
                "from": location_from_code,
                "to": location_to_code,
            },
        )
        raise

    log_action(
        ACTION_PUTAWAY_ACCEPTED,
        actor=operator,
        obj=move,
        metadata={
            "client_uuid": str(client_uuid),
            "detail": "",
            "from": location_from_code,
            "to": location_to_code,
        },
    )
    return move, OUTCOME_ACCEPTED


def _emplacement_interne(tenant: Tenant, code: str, role: str) -> StkLocation:
    """Un rangement va d'une etagere a une autre, jamais vers un
    emplacement virtuel.

    `resolve_scanned_location` accepte un code-barres de n'importe quel
    type d'emplacement : sans ce controle, un code de fournisseur ou de
    rebut scanne par erreur produirait un mouvement de nature toute autre
    que celle demandee. Le message NOMME le role fautif — depart ou
    destination — parce qu'un magasinier gante lit un refus en une seconde
    ou pas du tout."""
    location = resolve_scanned_location(tenant, code)
    if location is None:
        raise ValidationError(
            _("Emplacement de %(role)s introuvable : %(code)s") % {"role": role, "code": code}
        )
    if location.type != StkLocation.TYPE_INTERNE:
        raise ValidationError(
            _("L'emplacement de %(role)s « %(code)s » n'est pas un emplacement de stockage.")
            % {"role": role, "code": code}
        )
    return location
