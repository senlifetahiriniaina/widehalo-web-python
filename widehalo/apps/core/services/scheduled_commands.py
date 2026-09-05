"""L0 — socle des traitements periodiques.

L0-2 fournit ici la seule brique dont les commandes periodiques avaient
besoin et qu'une seule d'entre elles possedait : **l'isolation d'erreur par
tenant**.

`run_analytics_refresh` attrapait l'exception d'un tenant pour ne pas priver
les suivants de leur traitement ; les dix-huit autres la laissaient remonter
et **interrompaient la boucle**. Un seul tenant mal configure suffisait donc
a annuler le traitement de tous ceux qui le suivaient dans l'ordre de la
table — un defaut invisible tant que rien n'ordonnancait ces commandes, et
qui devient une panne silencieuse le jour ou elles tournent chaque nuit.

Le patron est repris de `run_analytics_refresh` plutot qu'invente : meme
message d'erreur, meme decision de continuer, un helper unique au lieu de
dix-huit `try/except` recopies.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


@contextmanager
def tenant_step(command: BaseCommand, tenant: Tenant) -> Iterator[None]:
    """Active le contexte du tenant et isole son echec.

    A utiliser en lieu et place de `activate_tenant(tenant.id)` dans la boucle
    d'une commande periodique. L'exception est signalee sur la sortie de la
    commande puis absorbee : le tenant suivant est traite.

    Volontairement large (`Exception`) : le but n'est pas de rattraper une
    faute precise mais d'empecher qu'un tenant en emporte dix-neuf autres. Une
    erreur de programmation reste visible — elle est ecrite, tenant par
    tenant, au lieu d'interrompre la nuit entiere."""
    try:
        with activate_tenant(tenant.id):
            yield
    except Exception as exc:  # noqa: BLE001 — un tenant en echec ne bloque jamais les suivants
        command.stdout.write(
            command.style.ERROR(f"Tenant {tenant.code} : échec du traitement ({exc}).")
        )
