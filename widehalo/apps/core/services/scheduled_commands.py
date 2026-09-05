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
from dataclasses import dataclass

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


# ---------------------------------------------------------------------------
# L0-3 — registre de planification
# ---------------------------------------------------------------------------
#
# Jusqu'ici, les cinquante-et-une commandes de gestion du depot attendaient un
# ordonnanceur qui n'existait pas : ni crontab, ni unite systemd, ni service
# dans `docker-compose.prod.yml` (qui ne lance que `web` et `worker`), ni objet
# `Schedule` django-q2. Dix-neuf d'entre elles sont periodiques ; le document de
# deploiement n'en nommait que trois, sans fournir de crontab.
#
# La consequence etait en chaine et invisible module par module : l'entrepot
# analytique n'etant jamais rafraichi, les modules BI, Forecast et Strategy
# restituaient des tableaux vides en exploitation, alors que chacun passe ses
# tests.
#
# Le registre suit le patron des neuf registres deja en place dans ce module
# (`reports_registry`, `automation_registry`, `data_query_tool_registry`...) :
# un dictionnaire en memoire peuple une fois au demarrage par les `ready()` des
# apps, jamais reinitialise en cours de vie du process. Il DECLARE ; c'est
# `apps.core.tasks` qui ECRIT les objets `Schedule`, seul fichier autorise a
# importer `django_q` (`tests/architecture/test_no_direct_task_queue_usage.py`).


FREQUENCY_HOURLY = "hourly"
FREQUENCY_DAILY = "daily"
FREQUENCY_WEEKLY = "weekly"
FREQUENCY_MONTHLY = "monthly"
FREQUENCY_CHOICES = (
    FREQUENCY_HOURLY,
    FREQUENCY_DAILY,
    FREQUENCY_WEEKLY,
    FREQUENCY_MONTHLY,
)


@dataclass(frozen=True)
class ScheduledCommand:
    """Une commande de gestion periodique et sa cadence.

    `hour` est la fenetre d'execution (heure locale du serveur) pour les
    cadences quotidiennes et au-dela : les traitements lourds sont pousses la
    nuit pour ne pas concurrencer l'usage interactif, contrainte que la
    Phase 3 avait deja posee pour ses traitements nocturnes."""

    code: str
    command: str
    module: str
    label: str
    frequency: str
    hour: int = 2
    description: str = ""


_SCHEDULE_REGISTRY: dict[str, ScheduledCommand] = {}


def register_scheduled_command(
    code: str,
    *,
    command: str,
    module: str,
    label: str,
    frequency: str,
    hour: int = 2,
    description: str = "",
) -> None:
    """Declare une commande periodique. Idempotent : un meme `code`
    re-enregistre remplace l'entree (utile au rechargement en developpement)."""
    if frequency not in FREQUENCY_CHOICES:
        raise ValueError(f"Cadence inconnue : {frequency!r} (attendu {FREQUENCY_CHOICES}).")
    if not 0 <= hour <= 23:
        raise ValueError(f"Heure invalide : {hour!r}.")
    _SCHEDULE_REGISTRY[code] = ScheduledCommand(
        code=code,
        command=command,
        module=module,
        label=label,
        frequency=frequency,
        hour=hour,
        description=description,
    )


def get_scheduled_command(code: str) -> ScheduledCommand | None:
    return _SCHEDULE_REGISTRY.get(code)


def list_scheduled_commands() -> list[ScheduledCommand]:
    return [_SCHEDULE_REGISTRY[code] for code in sorted(_SCHEDULE_REGISTRY)]


def schedule_registry_size() -> int:  # pragma: no cover — diagnostic
    return len(_SCHEDULE_REGISTRY)
