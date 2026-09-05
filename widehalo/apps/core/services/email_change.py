"""UXR1 — changement d'adresse e-mail confirme par lien a jeton (envoye par
e-mail), jamais une ecriture directe de `User.email` depuis l'ecran admin
(`apps.core.views.admin_users.admin_user_edit`) : `email` est
`USERNAME_FIELD` (identite de connexion), la modifier sans verifier que le
destinataire possede reellement cette boite mail romprait silencieusement
l'acces au compte.

**Simplification assumee (disclosed)** : un lien de confirmation a jeton
(pas un code numerique OTP saisi dans un formulaire) — mecanisme plus sur
et directement coherent avec le portail invite deja eprouve de ce depot
(`apps.projects.models.PrjGuestAccess` / `apps.projects.services.
guest_portal`), reutilise a l'identique ici pour `UserEmailChangeRequest`
(meme generateur de jeton `secrets.token_urlsafe(32)`, meme derogation RLS
`RLS_FORCE_FOR_OWNER = False`, meme discipline de rejet indiscernable — cf.
docstring de `UserEmailChangeRequest`).

`request_email_change` envoie un e-mail reel via `django.core.mail`, meme
patron que `apps.payroll.services.notify.send_payslip_by_email` (aucune
nouvelle dependance, SMTP deja configure au niveau settings)."""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.user import User, UserEmailChangeRequest

_TOKEN_BYTES = 32
_EXPIRY_HOURS = 24


def hash_token(token: str) -> str:
    """Empreinte stockee a la place du jeton (L15).

    Duplique volontairement `apps.projects.services.guest_portal.hash_token`
    plutot que de l'importer : `core` ne depend jamais d'un module metier
    (regle de couplage n°1 du modulith), et l'inverse — faire porter la
    fonction par `core` — ferait de `core` le proprietaire d'une primitive
    que les deux appelants pourraient vouloir faire diverger (rotation
    d'algorithme sur l'un sans l'autre). Trois lignes identiques valent mieux
    qu'une dependance qui n'a pas lieu d'etre."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_email_change(
    user: User, new_email: str, *, requested_by: User | None = None
) -> UserEmailChangeRequest:
    """Cree une demande de changement d'e-mail pour `user` et envoie le
    lien de confirmation a `new_email` (jamais a l'ancienne adresse — c'est
    la possession de la NOUVELLE boite mail qui doit etre verifiee). Le
    `token` est TOUJOURS genere ici (jamais fourni par l'appelant), meme
    discipline que `apps.projects.services.guest_portal.
    create_guest_access`.

    `tenant` (exige par `BaseModel`) : celui de `requested_by` si fourni
    (l'admin agit depuis un ecran deja tenant-scope), sinon celui de
    `user` (premiere societe active trouvee via `UserTenantMembership`) —
    ce champ ne porte ici qu'un role d'isolation/audit de la ligne, jamais
    de portee metier (un compte `User` est global, cf. docstring de
    `User`)."""
    tenant_id = None
    if requested_by is not None:
        membership = requested_by.tenant_memberships.order_by("-is_default").first()
        tenant_id = membership.tenant_id if membership else None
    if tenant_id is None:
        membership = user.tenant_memberships.order_by("-is_default").first()
        tenant_id = membership.tenant_id if membership else None
    if tenant_id is None:
        raise ValueError(
            _("Impossible de déterminer la société de la demande de changement d'e-mail.")
        )

    # L15 : la base ne porte que l'empreinte. Le jeton en clair n'existe que
    # dans cette variable et dans l'e-mail envoye — jamais en base, donc
    # jamais dans une sauvegarde.
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    change_request = UserEmailChangeRequest.objects.create(
        tenant_id=tenant_id,
        user=user,
        new_email=new_email,
        token_hash=hash_token(token),
        requested_by=requested_by,
        expires_at=timezone.now() + datetime.timedelta(hours=_EXPIRY_HOURS),
    )
    change_request.plaintext_token = token

    confirm_url = f"{settings.SITE_URL}/account/confirm-email/{token}/"
    message = EmailMessage(
        subject="Confirmez votre nouvelle adresse e-mail",
        body=(
            "Une demande de changement d'adresse e-mail a ete effectuee pour votre "
            "compte WideHalo. Pour confirmer cette nouvelle adresse, cliquez sur le "
            f"lien suivant (valable 24h) :\n\n{confirm_url}\n\n"
            "Si vous n'etes pas a l'origine de cette demande, ignorez cet e-mail."
        ),
        to=[new_email],
    )
    message.send(fail_silently=False)
    return change_request


def confirm_email_change(token: str) -> bool:
    """Confirme un changement d'e-mail depuis son `token`. Renvoie `False`,
    JAMAIS une exception, pour les 3 cas : token introuvable, deja
    confirme, ou expire — l'appelant (la vue publique `GET /account/
    confirm-email/<token>/`) ne doit RIEN pouvoir distinguer entre ces 3
    cas, meme discipline que `apps.projects.services.guest_portal.
    resolve_guest_access`. Utilise `all_objects` (jamais `objects`, filtre
    par tenant) : cette vue est publique, sans session ni tenant actif —
    cf. docstring de `UserEmailChangeRequest`."""
    if not token:
        return False
    change_request = UserEmailChangeRequest.all_objects.filter(token_hash=hash_token(token)).first()
    if change_request is None:
        return False
    if change_request.confirmed_at is not None:
        return False
    if change_request.expires_at <= timezone.now():
        return False

    user = change_request.user
    user.email = change_request.new_email
    user.save(update_fields=["email"])
    change_request.confirmed_at = timezone.now()
    change_request.save(update_fields=["confirmed_at"])
    return True
