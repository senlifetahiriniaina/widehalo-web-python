"""Motifs de perte d'opportunite par defaut, charges automatiquement a
l'initialisation d'une nouvelle entreprise (creation reelle de tenant —
commande `create_tenant`/ecran `setup_company_view`/reseed de reset).

**Taxonomie retenue** : les 7 categories metier de la « taxonomie
universelle recommandee » du document « Motifs de Perte d'Opportunite selon
les Top 5 CRM Mondiaux (2025-2026) » (analyse comparative Salesforce/
HubSpot/Microsoft Dynamics 365/SAP Sales Cloud/Oracle Fusion-NetSuite
fournie par l'utilisateur) — synthese explicite des 5 CRM analyses, avec une
recommandation centrale reprise a la lettre : « L'objectif doit etre une
liste de 5-7 raisons de perte... liees a des actions metier specifiques »
(une liste de 25 raisons y est documentee comme produisant des donnees
inutilisables : 75% des pertes finissent loggees sous "Price"/"Other" en 3
mois). Traduit en francais, repris tel quel (aucune sous-categorie —
celles-ci relevent du champ de commentaire libre `CrmLead.lost_comment`
deja existant, jamais un nouveau champ de sous-categorie).

**Idempotence** : `CrmLostReason` n'a aucune contrainte d'unicite en base
(ni `unique=True` sur `name`, ni `UniqueConstraint`) — `get_or_create(tenant=
tenant, name=label)` reste neanmoins deja idempotent par construction, meme
patron que `seed_crm.py` (qui cree deja son propre motif de demo « Prix trop
eleve » pour son tenant DEMO, sans jamais entrer en conflit avec ce
chargement, reserve aux tenants reels — cf. `pipelines.py`, meme
raisonnement de non-interference avec les scripts `seed_core`/`seed_crm`)."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.crm.models import CrmLostReason

DEFAULT_LOST_REASONS: tuple[str, ...] = (
    "Prix trop élevé",
    "Perdu face à un concurrent",
    "Absence de décision / projet abandonné",
    "Fonctionnalité manquante",
    "Perte de contact avec le décideur",
    "Mauvais timing",
    "Autre / raison inconnue",
)


def ensure_default_lost_reasons(tenant: Tenant) -> list[CrmLostReason]:
    """Cree les 7 motifs de perte par defaut pour ce tenant s'ils n'existent
    pas deja (idempotent par `(tenant, name)` — jamais de doublon, jamais
    d'ecrasement d'un motif deja edite par le tenant sous ce meme libelle)."""
    reasons = []
    for label in DEFAULT_LOST_REASONS:
        reason, _created = CrmLostReason.objects.get_or_create(tenant=tenant, name=label)
        reasons.append(reason)
    return reasons
