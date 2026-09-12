"""Fait expirer les devis dont la date de validite est passee.

**`expire_quotation` n'avait AUCUN appelant de production.** La fonction
existait, refusait correctement un devis qui n'est pas « envoye », et
personne ne pouvait la declencher : un devis dont la validite etait passee
restait « envoye » indefiniment. La relance commerciale et le taux de
conversion s'appuient sur cet etat.

**Pourquoi une commande ET un bouton.** L'expiration est un fait du
calendrier, pas une decision — d'ou la commande nocturne. Mais un
commercial qui constate qu'un devis est caduc doit pouvoir le dire sans
attendre la nuit, et c'est ce bouton qui rend la commande verifiable : sans
lui, la seule facon de constater que l'expiration marche serait d'attendre
le lendemain.

**Un devis sans date de validite n'expire jamais**, et c'est voulu :
l'absence de date dit « pas d'echeance », pas « echeance inconnue ».
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.sales.models import SalesQuotation
from apps.sales.services.quotations import expire_quotation


class Command(BaseCommand):
    help = "Fait expirer les devis envoyes dont la date de validite est passee."

    def handle(self, *args, **options) -> None:
        aujourd_hui = dt.date.today()
        total = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                caducs = SalesQuotation.objects.filter(
                    state=SalesQuotation.STATE_SENT,
                    validity_date__isnull=False,
                    validity_date__lt=aujourd_hui,
                    is_active=True,
                )
                for devis in caducs:
                    expire_quotation(devis)
                    total += 1
        self.stdout.write(self.style.SUCCESS(f"{total} devis expire(s)."))
