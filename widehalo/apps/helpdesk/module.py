from apps.core.module import ModuleSpec

# Chantier `helpdesk` (suivi des demandes et incidents operationnels, porte
# depuis l'ancienne version WideHalo Laravel — cf. plan, section « Module
# `helpdesk` »). Perimetre acte avec l'utilisateur : usage interne
# uniquement (aucun portail client/chat visiteur/forum), remplacement de
# toute fonctionnalite "modele ML entraine" par des regles deterministes.
#
# Dependance declaree : `core` UNIQUEMENT. Le rattachement "trace ecrite
# des dependances avec les operations" demande explicitement par
# l'utilisateur est satisfait par un lien GENERIQUE `content_type`/
# `object_id`/`content_object` sur `HlpTicket` (meme patron exact que
# `core.models.risk.RiskItem`/`core.models.quality.QltInspection`) — un
# ticket peut referencer N'IMPORTE QUEL enregistrement de N'IMPORTE QUEL
# module (`PurOrder`, `LogShipment`, `MrpOrder`, `StkQuant`...) SANS que
# `helpdesk` importe jamais un seul modele de ces apps. `django.contrib.
# contenttypes.models.ContentType` n'est PAS une violation de cette regle
# (table generique du socle Django, pas un modele metier d'une autre app),
# de meme pour `HlpTicketTypeCatalog.related_module` (simple CharField
# documentaire/indicatif, jamais une dependance declaree).
#
# HD3 ajoute deux dependances REELLES (consommation `services.public`
# uniquement, jamais un import de modele) :
# - `chat` : `apps.chat.services.public.get_or_create_document_channel`
#   (chat interne integre au detail ticket, cf. `views.py`) ;
# - `ai` : `apps.ai.services.public.get_budget_gated_provider`/
#   `record_request`/`estimate_tokens` (suggestion de reponse IA
#   fallback-first, cf. `services/ai_assist.py`).
MODULE = ModuleSpec(
    name="helpdesk",
    dependencies=("core", "chat", "ai"),
    verbose_name="Support et suivi operationnel",
)
