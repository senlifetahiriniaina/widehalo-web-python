"""Entites partenaire placeholder — chantier RG-QUALIF (qualification et
identification universelle des donnees importees). Un import qui reference
un partenaire par un nom libre non reconnu ne doit jamais bloquer la
ligne : la materialisation immediate se rabat sur un partenaire generique
"a qualifier" par role, et la ligne d'import qui l'utilise reste marquee
`needs_qualification` jusqu'a remplacement par le vrai partenaire
(`qualify_import_row`, cf. `apps.accounting.services.cash_journal_import`
et `apps.stocks.services.stock_import`)."""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.partners.models import Partner

_PLACEHOLDER_NAMES: dict[str, str] = {
    Partner.ROLE_CLIENT: _("Client à qualifier"),
    Partner.ROLE_SUPPLIER: _("Fournisseur à qualifier"),
    Partner.ROLE_CARRIER: _("Transporteur à qualifier"),
    Partner.ROLE_SUBCONTRACTOR: _("Sous-traitant à qualifier"),
}


def ensure_default_partner(tenant: Tenant, role: str) -> Partner:
    """Cree, s'il n'existe pas encore, LE partenaire placeholder de ce role
    pour ce tenant — get-or-create idempotent, un seul placeholder par
    (tenant, role) : un deuxieme appel avec le meme role renvoie toujours
    le meme enregistrement, jamais un doublon.

    `role` doit etre l'une des valeurs de `Partner.ROLE_CHOICES` — un role
    non reconnu de ce registre est une erreur de programmation de
    l'appelant (pas une donnee utilisateur), il n'y a donc pas de repli
    "role generique" : chaque module appelant sait deja quel role il
    cherche a defaulter (FOURNISSEUR sur une ligne SORTIE, CLIENT/PARTENAIRE
    sur une ligne ENTREE, cf. `cash_journal_import`)."""
    existing = Partner.objects.filter(
        tenant=tenant, is_placeholder=True, roles__contains=[role]
    ).first()
    if existing is not None:
        return existing

    reference = next_reference(tenant, "PARTPLC", timezone.now().year)
    return Partner.objects.create(
        tenant=tenant,
        reference=reference,
        name=str(_PLACEHOLDER_NAMES.get(role, _("Partenaire à qualifier"))),
        roles=[role],
        is_placeholder=True,
    )
