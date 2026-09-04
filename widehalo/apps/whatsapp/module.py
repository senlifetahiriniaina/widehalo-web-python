from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="whatsapp",
    # "chat" : conversation WhatsApp integree au chatter (WA-6) — reutilise
    # le canal generique de la Phase 1
    # (`chat.services.public.get_or_create_document_channel`), jamais un
    # second mecanisme de messagerie interne construit ici.
    dependencies=("core", "chat"),
    verbose_name="WhatsApp Business",
)
