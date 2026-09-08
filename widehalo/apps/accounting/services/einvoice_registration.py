"""T4 — la soumission part de la VALIDATION de la facture, par le bus.

**Pourquoi un abonné au bus et pas un appel dans `validate_invoice`.**
EFA-1 dit « une facture validée produit un document structuré » : le fait
déclencheur est la validation. Mais `validate_invoice` porte déjà la
chaîne d'approbation, la séparation des tâches ACH-9 et la publication de
l'écriture ; y ajouter la soumission ferait qu'un défaut du bloc C
remonterait dans le chemin de validation comptable — et FLX-2 interdit
précisément qu'un tiers mette en péril une transition métier.

Le bus donne la bonne forme : l'événement est persisté dans la MÊME
transaction que la validation, et distribué APRÈS commit. Une validation
qui échoue ne soumet rien ; une soumission qui échoue ne défait pas une
validation.

**L'abonné ne lève jamais pour un cas normal.** `submit_invoice` rend un
compte rendu plutôt que d'échouer sur une pièce hors du champ, un pays
sans profil ou un raccordement non ouvert — les trois sont l'état habituel
d'une installation, et le bus réessaie trois fois avant de marquer un
événement en échec. Faire lever ici sur un raccordement absent produirait
trois tentatives inutiles par facture, puis une trace d'échec pour un
fonctionnement nominal.
"""

from __future__ import annotations

from typing import Any

from apps.core.events import subscribe


def register_einvoice_subscribers() -> None:
    """Appelée depuis `apps.py::ready()`, même patron que les autres
    registres du module."""

    @subscribe("accounting.invoice_validated")
    def _on_invoice_validated(event: dict[str, Any]) -> None:
        from apps.accounting.models import AccMove
        from apps.accounting.services.einvoice_submission import submit_invoice

        move_id = (event.get("payload") or {}).get("move_id")
        if not move_id:
            return
        move = AccMove.objects.filter(id=move_id).first()
        if move is None:
            # La pièce a pu être supprimée entre la publication et la
            # distribution — rare, mais pas anormal, et re-lever ferait
            # réessayer trois fois quelque chose qui n'existe plus.
            return
        submit_invoice(move)


__all__ = ["register_einvoice_subscribers"]
