"""Contrat public de `logistics` — vide au demarrage du module (LOG1),
comme `sales.services.public`/`purchase.services.public` l'etaient a leur
premiere etape. Sera peuple au fil des etapes suivantes si un futur module
(aucun n'existe encore apres `logistics` dans l'ordre acte) a besoin de
consommer une donnee de ce module."""

from __future__ import annotations
