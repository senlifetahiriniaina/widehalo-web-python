from apps.core.module import ModuleSpec

# Chantier Qualite/HACCP (cahier Phase 3 §3.5) — application dediee, decidee
# avec l'utilisateur plutot qu'une fusion dans `apps.stocks` (decision D2,
# cf. `docs/planning/2026-09-adr-qualite-haccp-app-dediee.md`, l'ADR complet
# qui justifie ce choix et ce qu'il laisse explicitement en suspens pour le
# Bloc D).
#
# Squelette uniquement a ce stade (sprint P6 de la Vague 1) : aucun modele,
# aucun service reel encore livre — dependance declaree : `core` uniquement,
# pour l'instant. A completer au fil du Bloc D quand la vraie modelisation
# HACCP (plan/point critique, certificat, non-conformite bloquante, rappel)
# introduira de reelles consommations `services.public` d'autres apps
# (`purchase`/`mrp`/`sales`... references generiques `content_type`/
# `object_id`, jamais une FK directe — meme patron que `core.models.quality.
# QltInspection`).
MODULE = ModuleSpec(
    name="quality",
    dependencies=("core",),
    verbose_name="Qualite et HACCP",
)
