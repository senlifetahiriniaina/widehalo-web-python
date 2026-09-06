"""IA-9 (L7) — consentement a l'envoi de donnees vers un fournisseur d'IA
externe : ce qui sort, qui l'a accepte, et quand.

**Ce que ce module rend possible et qui ne l'etait pas.** L'activation d'un
fournisseur cloud etait une variable d'environnement posee au demarrage
(`AI_PROVIDER_CONFIG`). Elle n'etait ni consentie, ni datee, ni imputable :
aucun ecran, aucun modele, aucune entree d'audit. Un exploitant ne pouvait
pas repondre a « depuis quand les donnees de cette societe sortent-elles,
et qui l'a decide ? ».

Desormais, un fournisseur configure sans consentement du tenant retombe sur
le stub. La garantie « repli-d'abord » du module devient donc aussi une
garantie de confidentialite : par defaut, rien ne sort."""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai.models import AiExternalProviderConsent
from apps.core.models.tenant import Tenant
from apps.core.models.user import User


def outbound_data_disclosure() -> list[str]:
    """Ce qui QUITTE le serveur quand un fournisseur externe est actif.

    Le critere exige que l'activation « affiche EXPLICITEMENT quelles
    donnees sortiront du serveur ». Cette liste est deduite de ce que la
    passerelle transmet reellement — question de l'utilisateur, definitions
    des outils, et lignes retournees par les outils executes (cf.
    `data_query_gateway._run_tool_calling_loop`, qui construit `messages`)
    — jamais d'une formule marketing rassurante.

    Elle est volontairement redigee en termes de CE QUI EST ENVOYE, pas de
    ce qui est promis en retour : c'est la seule information sur laquelle
    un responsable peut fonder une decision."""
    return [
        str(_("La question posée, telle qu'elle est saisie, y compris les noms propres.")),
        str(
            _(
                "Le catalogue des rapports auxquels l'utilisateur a droit : leur nom, "
                "leur description et leurs paramètres."
            )
        ),
        str(
            _(
                "Les lignes de résultat des rapports que le fournisseur demande à "
                "consulter — chiffres d'affaires, marges, stocks, encours, selon la "
                "question et les droits de l'utilisateur."
            )
        ),
        str(
            _(
                "Aucun mot de passe, aucune clé, aucun fichier joint : la passerelle "
                "n'envoie que du texte qu'elle a elle-même composé."
            )
        ),
    ]


def active_consent(tenant: Tenant) -> AiExternalProviderConsent | None:
    """Le consentement en cours pour ce tenant, ou `None`.

    Un consentement revoque n'est jamais reactive : il reste en base comme
    trace, et une nouvelle acceptation cree une NOUVELLE ligne."""
    return (
        AiExternalProviderConsent.objects.filter(tenant=tenant, revoked_at__isnull=True)
        .order_by("-granted_at")
        .first()
    )


def has_active_consent(tenant: Tenant, *, backend: str) -> bool:
    """Le consentement couvre-t-il CE fournisseur ?

    Le `backend` est compare : un consentement donne pour un fournisseur
    ne vaut pas pour un autre. Changer de fournisseur cote deploiement
    redemande donc une acceptation, ce qui est le sens meme d'un
    consentement eclaire — la question « acceptez-vous que vos donnees
    partent chez X ? » n'a pas la meme reponse pour tout X."""
    consent = active_consent(tenant)
    return consent is not None and consent.backend == backend


def grant_consent(tenant: Tenant, *, backend: str, user: User | None) -> AiExternalProviderConsent:
    """Enregistre une acceptation, avec le texte EXACT presente.

    Idempotent pour un meme fournisseur : reaccepter ce qui est deja actif
    renvoie la ligne existante plutot que d'en empiler une seconde."""
    existing = active_consent(tenant)
    if existing is not None and existing.backend == backend:
        return existing
    if existing is not None:
        # Changement de fournisseur : l'ancien consentement est revoque,
        # jamais transfere.
        revoke_consent(tenant, user=user)
    return AiExternalProviderConsent.objects.create(
        tenant=tenant,
        backend=backend,
        granted_by=user,
        disclosure_text="\n".join(outbound_data_disclosure()),
    )


def revoke_consent(tenant: Tenant, *, user: User | None) -> AiExternalProviderConsent | None:
    """Revoque le consentement actif — la ligne reste, elle est datee.

    Retourne `None` s'il n'y en avait pas : revoquer ce qui n'est pas
    accorde n'est pas une erreur."""
    consent = active_consent(tenant)
    if consent is None:
        return None
    consent.revoked_at = timezone.now()
    consent.revoked_by = user
    consent.save(update_fields=["revoked_at", "revoked_by"])
    return consent
