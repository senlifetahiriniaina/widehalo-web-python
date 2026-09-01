"""Pipeline commercial par defaut, charge automatiquement a l'initialisation
d'une nouvelle entreprise (creation reelle d'un tenant — commande
`create_tenant`/ecran `setup_company_view`).

**Modele retenu** : le pipeline « Deal » a 7 etapes de HubSpot, tel que
documente dans « Modeles de pipeline des 5 principaux CRM mondiaux
(2025-2026) » (analyse comparative Salesforce/Microsoft Dynamics 365/
HubSpot/SAP Sales Cloud/Oracle Fusion fournie par l'utilisateur) — cite
explicitement dans le TL;DR de ce document comme *le modele de pipeline par
defaut le plus repandu du marche* (« Le modele par defaut le plus repandu
est un pipeline de 7 etapes chez HubSpot »), avec ses probabilites de
cloture documentees par defaut (20/40/60/80/90/100/0%). Traduit en francais,
repris tel quel (aucune adaptation sectorielle) : c'est un point de depart
editable par l'entreprise via l'ecran de configuration existant
(`crm:config_pipelines`), jamais une prescription figee.

**Idempotence par tenant, pas par nom** : `ensure_default_pipeline` reutilise
tout pipeline deja marque `is_default=True` pour ce tenant, quelle qu'en soit
l'origine, plutot que de matcher sur le nom `DEFAULT_PIPELINE_NAME` — evite
qu'un second pipeline « par defaut » ne soit cree en doublon si l'entreprise
a deja le sien.

**Volontairement non branche sur `seed_core`/`seed_crm`** (les commandes de
jeu de demonstration T10) : `seed_crm.py` cree deja son propre pipeline de
demonstration a 5 etapes (nomme differemment, marque `is_default=True` lui
aussi) pour le tenant `DEMO` — brancher ce chargement automatique sur
`seed_core.py` en plus creerait deux pipelines `is_default=True` pour ce
meme tenant et casserait l'hypothese d'unicite du test
`test_seed_crm_creates_coherent_demo_dataset`
(`CrmPipeline.objects.get(tenant=tenant, is_default=True)`). Ce chargement
automatique ne s'applique donc qu'a une initialisation reelle d'entreprise,
jamais aux scripts de demonstration/test."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.crm.models import CrmPipeline, CrmStage

DEFAULT_PIPELINE_NAME = "Pipeline commercial par defaut"

# (code, nom, sequence, probabilite %, gagne, perdu, motif requis) — HubSpot
# Deal pipeline par defaut (7 etapes), probabilites documentees dans le
# document source cite ci-dessus.
DEFAULT_STAGES: tuple[tuple[str, str, int, int, bool, bool, bool], ...] = (
    ("appointment_scheduled", "Rendez-vous planifie", 1, 20, False, False, False),
    ("qualified_to_buy", "Qualifie pour achat", 2, 40, False, False, False),
    ("presentation_scheduled", "Presentation planifiee", 3, 60, False, False, False),
    ("decision_maker_bought_in", "Decideur convaincu", 4, 80, False, False, False),
    ("contract_sent", "Contrat envoye", 5, 90, False, False, False),
    ("closed_won", "Gagne", 6, 100, True, False, False),
    ("closed_lost", "Perdu", 7, 0, False, True, True),
)


def ensure_default_pipeline(tenant: Tenant) -> CrmPipeline:
    """Reutilise le pipeline `is_default=True` deja present pour ce tenant
    s'il en existe deja un, sinon cree le pipeline HubSpot a 7 etapes
    decrit ci-dessus (7 `CrmStage`, jamais recrees si deja presents —
    `get_or_create` par code)."""
    existing = CrmPipeline.objects.filter(tenant=tenant, is_default=True).first()
    if existing is not None:
        return existing

    pipeline = CrmPipeline.objects.create(
        tenant=tenant, name=DEFAULT_PIPELINE_NAME, is_default=True
    )
    for code, name, sequence, probability, is_won, is_lost, requires_reason in DEFAULT_STAGES:
        CrmStage.objects.get_or_create(
            tenant=tenant,
            pipeline=pipeline,
            code=code,
            defaults={
                "name": name,
                "sequence": sequence,
                "probability": probability,
                "is_won": is_won,
                "is_lost": is_lost,
                "requires_reason": requires_reason,
            },
        )
    return pipeline
