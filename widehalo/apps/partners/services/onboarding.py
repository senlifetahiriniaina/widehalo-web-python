from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.fiscal_identifiers import canonical
from apps.core.services.sequences import next_reference
from apps.partners.models import DuplicateAlert, Partner


def create_partner(
    *,
    tenant: Tenant,
    name: str,
    roles: list[str],
    nif: str = "",
    stat: str = "",
    credit_limit_mga: Decimal = Decimal(0),
) -> Partner:
    """Cree un partenaire avec un code auto-sequence (PART-<annee>-NNNN) et
    detecte un eventuel doublon de NIF DANS LE MEME TENANT sans jamais
    bloquer la creation — le rapprochement porte depuis T3 sur la forme
    CANONIQUE de l'identifiant (`fiscal_identifiers.canonical`), et non
    plus sur la chaine brute — une `DuplicateAlert` est simplement journalisee
    pour revue humaine.

    **INT1 (chantier interactivite native inter-modules)** : chaque
    `DuplicateAlert` creee publie `partners.duplicate_alert_created` (meme
    patron que `core.services.risk._maybe_publish_flagged` — persistance
    metier d'abord, `publish_event` ensuite), pour qu'un flux du Studio de
    workflow visuel puisse notifier le role responsable de la revue des
    doublons sans modification de ce module."""
    reference = next_reference(tenant, "PART", timezone.now().year)

    partner = Partner.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        roles=roles,
        nif=nif,
        stat=stat,
        credit_limit_mga=credit_limit_mga,
    )

    if partner.nif:
        from apps.core.events import publish_event

        # T3 — le rapprochement se fait sur la forme CANONIQUE, pas sur la
        # chaîne brute. Avant ce lot, « MG-NIF-100002 » et « mg nif 100002 »
        # désignaient le même tiers et ne levaient aucune alerte : la
        # détection de doublon ne voyait que les saisies rigoureusement
        # identiques, c'est-à-dire le cas où l'utilisateur avait déjà fait
        # attention.
        # Le rapprochement se fait en Python et non en SQL, faute d'index
        # fonctionnel sur la forme canonique — et la requete ne ramene donc
        # que les deux colonnes utiles des seules fiches qui portent un NIF,
        # jamais tout le referentiel. Comparer en base supposerait de
        # reproduire `canonical` en SQL, ce qui divergerait sur les valeurs
        # anterieures a T3 : aucune migration de donnees ne les a
        # normalisees (deliberement — cf. la migration), et elles peuvent
        # donc contenir des caracteres que le format n'admet plus.
        cible = canonical(partner.nif)
        existing_matches = [
            autre
            for autre in (
                Partner.objects.filter(tenant=tenant)
                .exclude(pk=partner.pk)
                .exclude(nif="")
                .only("id", "nif")
            )
            if canonical(autre.nif) == cible
        ]
        for match in existing_matches:
            alert = DuplicateAlert.objects.create(
                tenant=tenant, partner=partner, duplicate_of=match, matched_field="nif"
            )
            publish_event(
                "partners.duplicate_alert_created",
                {
                    "alert_id": str(alert.id),
                    "partner_id": str(partner.id),
                    "duplicate_of_id": str(match.id),
                    "matched_field": alert.matched_field,
                },
                tenant_id=str(tenant.id),
            )

    return partner
