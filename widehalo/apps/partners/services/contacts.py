from __future__ import annotations

from apps.partners.models import Partner, PartnerContact


def create_contact(
    *,
    partner: Partner,
    full_name: str,
    role: str = "",
    title: str = "",
    email: str = "",
    phone: str = "",
    is_primary: bool = False,
) -> PartnerContact:
    return PartnerContact.objects.create(
        tenant=partner.tenant,
        partner=partner,
        full_name=full_name,
        role=role,
        title=title,
        email=email,
        phone=phone,
        is_primary=is_primary,
    )


def update_contact(
    contact: PartnerContact,
    *,
    full_name: str,
    role: str = "",
    title: str = "",
    email: str = "",
    phone: str = "",
    is_primary: bool = False,
) -> PartnerContact:
    contact.full_name = full_name
    contact.role = role
    contact.title = title
    contact.email = email
    contact.phone = phone
    contact.is_primary = is_primary
    contact.full_clean()
    contact.save()
    return contact


def list_contacts(partner: Partner, *, role: str = "") -> list[PartnerContact]:
    """Contacts pertinents pour un onglet donne : un contact `role=""` est
    general (visible sur tous les onglets), un contact `role=<code>` n'est
    visible que sur l'onglet correspondant. `role=""` en argument renvoie
    tous les contacts (onglet General)."""
    queryset = partner.contacts.all().order_by("-is_primary", "full_name")
    if not role:
        return list(queryset)
    return [c for c in queryset if c.role in ("", role)]
