"""T4 (bloc C, EFA-8) — signer une soumission, et refuser de le faire avec
un certificat périmé.

**Le critère** : « L'expiration prochaine du certificat de signature
déclenche une alerte au moins trente jours avant échéance ; une signature
avec certificat expiré est **refusée avant soumission**. »

**Pourquoi ce module vit dans `flows` et pas dans `accounting`.** La clef
privée est un secret, et le cahier est catégorique sur son logement
(§13.2) : « table à part, chiffrée, jamais exportée, jamais lue par le
copilote ». Elle vit donc dans `FlwCredential`, qui appartient à ce
module. Si `accounting` devait signer lui-même, il faudrait lui rendre la
clef — c'est-à-dire faire traverser un secret à une frontière de module
pour qu'il soit utilisé ailleurs. Ce module rend donc la SIGNATURE, jamais
la clef : ce qui sort est le résultat, ce qui reste est le moyen.

**Le produit consomme un certificat, il n'en émet pas** (§2.6 : « le
produit consomme un certificat de signature électronique fourni par le
client ou par un prestataire ; il n'en émet pas et n'en gère pas le cycle
de vie au-delà de l'alerte d'expiration »). Aucune génération de clef ici,
aucune autorité de certification, aucun renouvellement automatique.

**Réserve sur le FORMAT de signature.** Le dispositif malgache n'étant pas
ouvert, la forme exacte attendue — signature détachée, enveloppée, XAdES,
CAdES — n'est publiée nulle part d'accessible à ce dépôt. Ce module produit
une signature DÉTACHÉE RSA-PSS/SHA-256 sur les octets soumis, et
l'algorithme est nommé dans le résultat plutôt que supposé par l'appelant.
Ce qui est tenu, et qui est ce que le critère demande, est indépendant de
cette forme : une signature est produite, elle porte l'empreinte de ce qui
part, et un certificat périmé la refuse. La forme se change ici, sans
toucher à l'appelant.
"""

from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.flows.models import FlwCredential, FlwLink

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

#: Le préavis d'alerte, en jours. Le critère dit « AU MOINS trente jours » :
#: c'est un plancher, pas une cible. Trente exactement laisse un mois pour
#: obtenir un renouvellement auprès d'une autorité, ce qui est court ; la
#: constante existe pour qu'un déploiement puisse l'élargir sans toucher au
#: code qui la lit.
EXPIRY_WARNING_DAYS = 30

#: Nommé dans le résultat plutôt que supposé : le jour où une plateforme
#: réelle exigera autre chose, l'appelant verra que la forme a changé au
#: lieu de transmettre en silence une signature qu'elle refusera.
SIGNATURE_ALGORITHM = "RSASSA-PSS-SHA256"


@dataclass(frozen=True)
class CertificateStatus:
    """Ce qu'on peut dire d'un certificat SANS révéler quoi que ce soit.

    Aucun champ ne porte de matière secrète : un libellé, une date, un
    indice déjà prévu pour l'affichage (`FlwCredential.secret_hint`, « se
    termine par 4f2a »). C'est ce qu'un écran peut montrer, et c'est ce que
    `accounting` a le droit de lire."""

    present: bool
    label: str = ""
    hint: str = ""
    expires_at: dt.datetime | None = None
    expired: bool = False
    days_remaining: int | None = None

    @property
    def expiring_soon(self) -> bool:
        """Vrai dans la fenêtre d'alerte, faux une fois périmé.

        Un certificat DÉJÀ périmé n'expire pas « bientôt » : il est
        expiré, et c'est un autre message, une autre urgence et un autre
        écran. Les confondre ferait afficher « expire dans -3 jours »."""
        if self.expired or self.days_remaining is None:
            return False
        return self.days_remaining <= EXPIRY_WARNING_DAYS


@dataclass(frozen=True)
class Signature:
    """Une signature détachée, et de quoi savoir ce qu'elle vaut."""

    algorithm: str
    value: str
    certificate_hint: str
    signed_at: dt.datetime


def certificate_status(
    tenant: Tenant, *, connector_code: str, now: dt.datetime | None = None
) -> CertificateStatus:
    """L'état du certificat servant ce connecteur pour ce tenant.

    `present=False` quand il n'y en a pas : ne pas avoir encore fourni son
    certificat est l'état normal de toute installation qui n'a pas ouvert
    de raccordement, pas une anomalie à signaler."""
    credential = _find_certificate(tenant, connector_code)
    if credential is None:
        return CertificateStatus(present=False)

    maintenant = now or timezone.now()
    if credential.expires_at is None:
        # Un certificat sans échéance connue n'est pas réputé éternel : il
        # est réputé NON SURVEILLÉ. On ne le refuse pas — refuser
        # bloquerait une soumission sur une donnée que l'exploitant a
        # seulement omis de saisir — mais aucune alerte ne peut être émise
        # à son sujet, et `days_remaining` le dit en restant nul.
        return CertificateStatus(present=True, label=credential.label, hint=credential.secret_hint)

    restant = (credential.expires_at - maintenant).days
    return CertificateStatus(
        present=True,
        label=credential.label,
        hint=credential.secret_hint,
        expires_at=credential.expires_at,
        expired=credential.expires_at <= maintenant,
        days_remaining=restant,
    )


def sign_payload(
    tenant: Tenant, *, connector_code: str, payload: bytes, now: dt.datetime | None = None
) -> Signature | None:
    """Signe les octets soumis, ou refuse.

    Rend `None` quand aucun certificat n'est fourni — l'installation qui
    n'a pas encore de raccordement produit et archive quand même son
    document (EFA-2), elle ne peut simplement pas le signer, et ce n'est
    pas une erreur à présenter.

    LÈVE, en revanche, sur un certificat PÉRIMÉ : le critère l'exige
    (« refusée avant soumission »), et la différence avec le cas précédent
    est celle entre « pas encore équipé » et « équipé d'un moyen qui n'a
    plus de valeur ». Signer avec un certificat périmé produirait une
    soumission que l'administration rejettera, après l'avoir enregistrée."""
    credential = _find_certificate(tenant, connector_code)
    if credential is None:
        return None

    maintenant = now or timezone.now()
    if credential.expires_at is not None and credential.expires_at <= maintenant:
        raise ValidationError(
            _(
                "Certificat de signature expiré le %(date)s : la soumission est "
                "refusée avant d'être émise. Renouvelez le certificat auprès de "
                "votre autorité, puis relancez la soumission."
            )
            % {"date": credential.expires_at.date().isoformat()}
        )

    return Signature(
        algorithm=SIGNATURE_ALGORITHM,
        value=_detached_signature(credential.secret, payload),
        certificate_hint=credential.secret_hint,
        signed_at=maintenant,
    )


def _find_certificate(tenant: Tenant, connector_code: str) -> FlwCredential | None:
    """Le certificat porté par une liaison ACTIVE de ce tenant.

    C'est la LIAISON qui est interrogée, jamais le connecteur seul : sur
    une instance multi-sociétés, deux tenants branchés sur le même
    adaptateur ont deux enrôlements et deux certificats. Lire le connecteur
    ferait signer une société avec le certificat d'une autre."""
    liaison = (
        FlwLink.objects.filter(
            tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
        )
        .select_related("connector")
        .first()
    )
    if liaison is None:
        return None
    return FlwCredential.objects.filter(
        tenant=tenant, connector=liaison.connector, kind=FlwCredential.KIND_CERTIFICATE
    ).first()


def _detached_signature(private_key_pem: str, payload: bytes) -> str:
    """RSA-PSS/SHA-256 sur les octets, rendue en base64.

    La clef est lue, utilisée et abandonnée dans cette fonction ; elle ne
    remonte jamais à l'appelant, ne figure dans aucun retour et n'est
    jamais journalisée — la redaction de S6 couvre les journaux, mais le
    meilleur moyen qu'un secret ne fuie pas est qu'il ne circule pas."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        cle = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError) as refus:
        raise ValidationError(
            _(
                "Le certificat enregistré n'est pas une clé privée lisible : la "
                "soumission est refusée avant d'être émise. Vérifiez le fichier "
                "fourni par votre autorité de certification."
            )
        ) from refus

    if not isinstance(cle, rsa.RSAPrivateKey):
        raise ValidationError(
            _(
                "Le certificat enregistré n'est pas une clé RSA : c'est le seul "
                "type que ce dispositif sait signer aujourd'hui."
            )
        )

    signature = cle.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


__all__ = [
    "EXPIRY_WARNING_DAYS",
    "SIGNATURE_ALGORITHM",
    "CertificateStatus",
    "Signature",
    "certificate_status",
    "sign_payload",
]
